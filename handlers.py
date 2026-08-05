from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from datetime import date, timedelta
import calendar as pycalendar

import database as db

router = Router()

# --- СТАНИ (FSM) ДЛЯ СТВОРЕННЯ КЛІЄНТА ТА ЗАВДАННЯ ---

class CreateClient(StatesGroup):
    waiting_for_phone = State()
    waiting_for_first_name = State()
    waiting_for_last_name = State()
    waiting_for_address = State()

class CreateOrder(StatesGroup):
    selecting_client = State()
    waiting_for_title = State()
    building_items = State()
    item_type = State()
    item_name = State()
    item_unit = State()
    item_price = State()
    item_quantity = State()

# --- ГОЛОВНЕ МЕНЮ ТА КЛАВІАТУРИ ---

def main_keyboard():

    kb = [
        [KeyboardButton(text="➕ Нове завдання")],
        [
            KeyboardButton(text="⏳ Завдання в роботі"),
            KeyboardButton(text="📁 Виконані завдання"),
        ],
        [KeyboardButton(text="📊 Статистика")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def cancel_kb(show_skip: bool = False):
    buttons = []
    if show_skip:
        buttons.append([KeyboardButton(text="⏩ Пропустити")])
    buttons.append([KeyboardButton(text="❌ Скасувати")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# --- 0. УНІВЕРСАЛЬНЕ СКАСУВАННЯ ---

@router.message(F.text.lower().in_(["❌ скасувати", "/cancel", "скасувати"]))

@router.callback_query(F.data == "cancel_action")

async def cancel_handler(
    event: types.Message | types.CallbackQuery, state: FSMContext
):

    current_state = await state.get_state()

    if current_state is None:
        if isinstance(event, types.Message):
            await event.answer(
                "Немає активного процесу для скасування.",
                reply_markup=main_keyboard(),
            )
        return

    await state.clear()
    text = "❌ Процес скасовано. Повертаємось у головне меню."

    if isinstance(event, types.CallbackQuery):
        await event.message.delete()
        await event.message.answer(text, reply_markup=main_keyboard())
    else:
        await event.answer(text, reply_markup=main_keyboard())

# --- 1. КРОК: НАТИСКАННЯ "➕ НОВЕ ЗАВДАННЯ" ---

async def show_client_selection(event: types.Message | types.CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    clients = await db.get_user_clients_with_order_count(user_id)

    kb = []
    for client_id, first_name, last_name, phone, order_count in clients:
        full_name = f"{first_name} {last_name or ''}".strip()
        row = [
            InlineKeyboardButton(
                text=f"👤 {full_name} ({phone})",
                callback_data=f"select_client_{client_id}",
            )
        ]
        if order_count == 0:
            row.append(
                InlineKeyboardButton(text="🗑 Видалити", callback_data=f"confirm_delete_client_{client_id}")
            )
        kb.append(row)

    kb.append(
        [
            InlineKeyboardButton(
                text="➕ Додати нового замовника",
                callback_data="add_new_client",
            )
        ]
    )
    kb.append(
        [
            InlineKeyboardButton(
                text="❌ Скасувати", callback_data="cancel_action"
            )
        ]
    )

    text = "👤 **Обери замовника зі списку або додай нового:**\n<i>Кнопкою \"Видалити\" позначені замовники без жодного завдання.</i>"

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
    else:
        await event.answer(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )


@router.message(F.text == "➕ Нове завдання")

async def start_new_order(message: types.Message, state: FSMContext):
    await state.set_state(CreateOrder.selecting_client)
    await show_client_selection(message, state)


# --- ВИДАЛЕННЯ ЗАМОВНИКА БЕЗ ЗАВДАНЬ ---

@router.callback_query(F.data.startswith("confirm_delete_client_"))
async def confirm_delete_client_dialog(callback: types.CallbackQuery):
    client_id = int(callback.data.split("_")[3])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ Так, видалити", callback_data=f"delete_client_now_{client_id}"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_delete_client"),
        ]
    ])
    await callback.message.edit_text(
        "❓ **Видалити цього замовника?**\nЦю дію не можна скасувати.",
        parse_mode="Markdown",
        reply_markup=kb,
    )


@router.callback_query(F.data == "cancel_delete_client")
async def cancel_delete_client_handler(callback: types.CallbackQuery, state: FSMContext):
    await show_client_selection(callback, state)


@router.callback_query(F.data.startswith("delete_client_now_"))
async def delete_client_action(callback: types.CallbackQuery, state: FSMContext):
    client_id = int(callback.data.split("_")[3])
    success = await db.delete_client(client_id, callback.from_user.id)

    if success:
        await callback.answer("✅ Замовника видалено!", show_alert=True)
    else:
        await callback.answer(
            "❌ Не вдалося видалити — з цим замовником вже пов'язане завдання.",
            show_alert=True,
        )

    await show_client_selection(callback, state)

# --- 2. ПОКРОКОВЕ ДОДАВАННЯ НОВОГО ЗАМОВНИКА ---

@router.callback_query(
    CreateOrder.selecting_client, F.data == "add_new_client"
)

async def process_add_client_start(
    callback: types.CallbackQuery, state: FSMContext
):
    await state.set_state(CreateClient.waiting_for_phone)
    await callback.message.delete()
    await callback.message.answer(
        "📱 **Введи номер телефону замовника** (або надішли його як контакт з Telegram):",
        parse_mode="Markdown",
        reply_markup=cancel_kb(show_skip=False),
    )

@router.message(CreateClient.waiting_for_phone)
async def process_client_phone(message: types.Message, state: FSMContext):

    if message.contact:
        phone = message.contact.phone_number
        first_name = message.contact.first_name or ""
        last_name = message.contact.last_name or ""
        await state.update_data(
            phone=phone, first_name=first_name, last_name=last_name
        )

    else:
        phone = message.text.strip()
        await state.update_data(phone=phone)

    data = await state.get_data()

    if data.get("first_name"):
        await state.set_state(CreateClient.waiting_for_address)
        await message.answer(
            f"Отримано контакт: *{data['first_name']} {data.get('last_name', '')}* ({phone})\n\n"
            f"🏠 Введи **адресу** замовника (або натисни 'Пропустити'):",
            parse_mode="Markdown",
            reply_markup=cancel_kb(show_skip=True),
        )

    else:
        await state.set_state(CreateClient.waiting_for_first_name)
        await message.answer(
            "👤 Введи **ім'я** замовника (Обов'язково):",
            parse_mode="Markdown",
            reply_markup=cancel_kb(show_skip=False),
        )


@router.message(CreateClient.waiting_for_first_name)
async def process_client_first_name(message: types.Message, state: FSMContext):
    await state.update_data(first_name=message.text.strip())
    await state.set_state(CreateClient.waiting_for_last_name)
    await message.answer(
        "👤 Введи **прізвище** замовника (або натисни 'Пропустити'):",
        parse_mode="Markdown",
        reply_markup=cancel_kb(show_skip=True),
    )

@router.message(CreateClient.waiting_for_last_name)
async def process_client_last_name(message: types.Message, state: FSMContext):
    last_name = "" if message.text == "⏩ Пропустити" else message.text.strip()
    await state.update_data(last_name=last_name)
    await state.set_state(CreateClient.waiting_for_address)
    await message.answer(
        "🏠 Введи **адресу** замовника (або натисни 'Пропустити'):",
        parse_mode="Markdown",
        reply_markup=cancel_kb(show_skip=True),
    )


@router.message(CreateClient.waiting_for_address)
async def process_client_address(message: types.Message, state: FSMContext):
    address = "" if message.text == "⏩ Пропустити" else message.text.strip()
    data = await state.get_data()
    phone = data.get("phone") or "Не вказано"
    first_name = data.get("first_name") or "Замовник"
    last_name = data.get("last_name", "")

    # Зберігаємо тимчасові дані замовника у FSM (в БД НЕ записуємо!)

    temp_client = {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "address": address,
    }

    await state.update_data(temp_client=temp_client, client_id=None, items=[])
    await state.set_state(CreateOrder.waiting_for_title)
    await message.answer(
        f"✅ Дані замовника *{first_name}* отримано!\n\n"
        f"📝 Тепер введи **коротку назву (суть) завдання** (наприклад, *Ремонт ПК Asus*):",
        parse_mode="Markdown",
        reply_markup=cancel_kb(show_skip=False),
    )


# --- 3. ОБРАНО ІСНУЮЧОГО КЛІЄНТА ---

@router.callback_query(
    CreateOrder.selecting_client, F.data.startswith("select_client_")
)

async def process_select_existing_client(
    callback: types.CallbackQuery, state: FSMContext
):
    client_id = int(callback.data.split("_")[2])
    await state.update_data(client_id=client_id, temp_client=None, items=[])
    await state.set_state(CreateOrder.waiting_for_title)
    await callback.message.delete()
    await callback.message.answer(
        "📝 Введи **коротку назву (суть) завдання** (наприклад, *Монтаж Reels*):",
        parse_mode="Markdown",
        reply_markup=cancel_kb(show_skip=False),
    )

# --- 4. ВВЕДЕННЯ НАЗВИ ЗАВДАННЯ ТА КОНСТРУКТОР КОШТОРИСУ ---

@router.message(CreateOrder.waiting_for_title)
async def process_order_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await show_items_constructor(message, state)

async def show_items_constructor(
    event: types.Message | types.CallbackQuery, state: FSMContext
):
    data = await state.get_data()
    title = data.get("title", "")
    items = data.get("items", [])
    text = f"📋 **Завдання:** {title}\n\n"

    if not items:
        text += "<i>Позицій ще не додано.</i>\n\n"
    else:
        text += "<b>Складники кошторису:</b>\n"
        total_work = 0
        total_mat = 0

        for i, item in enumerate(items, 1):
            icon = "🛠" if item["item_type"] == "work" else "📦"
            cost = item["unit_price"] * item["quantity"]

            if item["item_type"] == "work":
                total_work += cost
            else:
                total_mat += cost

            text += f"{i}. {icon} {item['name']} — {item['quantity']} {item['unit']} × {item['unit_price']} грн = <b>{cost:.2f} грн</b>\n"

        text += f"\n💳 **Разом до сплати:** {total_work + total_mat:.2f} грн\n"
        text += f"📉 **Витрати (матеріали):** {total_mat:.2f} грн\n"
        text += f"💰 **Чистий прибуток:** {total_work:.2f} грн\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Додати роботу",
                    callback_data="add_item_type_work",
                ),

                InlineKeyboardButton(
                    text="📦 Додати матеріал",
                    callback_data="add_item_type_material",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Зберегти замовлення",
                    callback_data="save_final_order",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати створення", callback_data="cancel_action"
                )
            ],
        ]
    )

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(
            text, parse_mode="HTML", reply_markup=kb
        )
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb)


# --- 5. ПОКРОКОВЕ ДОДАВАННЯ ПОЗИЦІЇ (РОБОТА / МАТЕРІАЛ) ---

@router.callback_query(F.data.startswith("add_item_type_"))
async def start_add_item(callback: types.CallbackQuery, state: FSMContext):
    item_type = callback.data.split("_")[3]
    await state.update_data(current_item_type=item_type)
    await state.set_state(CreateOrder.item_name)
    type_str = "роботи" if item_type == "work" else "матеріалу"
    await callback.message.answer(
        f"🔹 Введи **назву** {type_str}:",
        reply_markup=cancel_kb(show_skip=False),
    )

@router.message(CreateOrder.item_name)
async def process_item_name(message: types.Message, state: FSMContext):
    await state.update_data(current_item_name=message.text.strip())
    await state.set_state(CreateOrder.item_unit)
    units_kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="шт"),
                KeyboardButton(text="год"),
                KeyboardButton(text="послуга"),
            ],
            [
                KeyboardButton(text="м²"),
                KeyboardButton(text="комплект"),
            ],
            [KeyboardButton(text="❌ Скасувати")],
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "📐 Вкажи **одиницю виміру** (наприклад: *шт*, *год*, *послуга* або обери з кнопок):",
        parse_mode="Markdown",
        reply_markup=units_kb,
    )

@router.message(CreateOrder.item_unit)
async def process_item_unit(message: types.Message, state: FSMContext):
    await state.update_data(current_item_unit=message.text.strip())
    await state.set_state(CreateOrder.item_price)
    await message.answer(
        "💰 Вкажи **ціну за одиницю (у грн)**:",
        reply_markup=cancel_kb(show_skip=False),
    )

@router.message(CreateOrder.item_price)
async def process_item_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        await state.update_data(current_item_price=price)
        await state.set_state(CreateOrder.item_quantity)
        await message.answer(
            "🔢 Вкажи **кількість**:", reply_markup=cancel_kb(show_skip=False)
        )
    except ValueError:
        await message.answer("❌ Будь ласка, введи число! Спробуй ще раз:")

@router.message(CreateOrder.item_quantity)
async def process_item_quantity(message: types.Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
        data = await state.get_data()
        new_item = {
            "item_type": data["current_item_type"],
            "name": data["current_item_name"],
            "unit": data["current_item_unit"],
            "unit_price": data["current_item_price"],
            "quantity": qty,
        }
        items = data.get("items", [])
        items.append(new_item)
        await state.update_data(items=items)
        await state.set_state(CreateOrder.building_items)
        await show_items_constructor(message, state)

    except ValueError:
        await message.answer("❌ Будь ласка, введи число! Спробуй ще раз:")

# --- 6. ФІНАЛЬНЕ ЗБЕРЕЖЕННЯ ЗАМОВЛЕННЯ ---

@router.callback_query(F.data == "save_final_order")
async def save_order_to_db(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    items = data.get("items", [])

    if not items:
        await callback.answer(
            "⚠️ Додай хоча б одну позицію (роботу чи матеріал)!",
            show_alert=True,
        )
        return

    client_id = data.get("client_id")
    temp_client = data.get("temp_client")

    # Якщо додавали нового замовника — зберігаємо його в БД ТІЛЬКИ ЗАРАЗ

    if not client_id and temp_client:
        client_id = await db.add_client(
            user_id=callback.from_user.id,
            first_name=temp_client["first_name"],
            phone=temp_client["phone"],
            last_name=temp_client["last_name"],
            address=temp_client["address"],
        )

    order_id = await db.create_order(
        user_id=callback.from_user.id,
        client_id=client_id,
        title=data["title"],
        items=items,
    )
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        f"🎉 **Завдання №{order_id} успішно створено та додано в роботу!**",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# --- ПЕРЕГЛЯД ЗАВДАНЬ В РОБОТІ ---

@router.message(F.text == "⏳ Завдання в роботі")
async def show_in_progress_orders(message: types.Message):
    orders = await db.get_user_orders(message.from_user.id, status='in_progress')

    if not orders:
        await message.answer(
            "📭 У вас немає активних завдань у роботі.",
            reply_markup=main_keyboard()
        )
        return

    kb = []

    for order_id, title, first_name, last_name, _ in orders:
        client_str = f" ({first_name} {last_name or ''})".strip() if first_name else ""
        kb.append([
            InlineKeyboardButton(
                text=f"📌 №{order_id}: {title}{client_str}",
                callback_data=f"view_order_{order_id}"
            )
        ])

    await message.answer(
        "⏳ **Завдання в роботі:**\nОбери завдання для перегляду детальної інформації:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

# --- ПЕРЕГЛЯД ВИКОНАНИХ ЗАВДАНЬ ---

@router.message(F.text == "📁 Виконані завдання")
async def show_completed_orders(message: types.Message):
    orders = await db.get_user_orders(message.from_user.id, status='completed')

    if not orders:
        await message.answer(
            "📭 У вас ще немає виконаних завдань.",
            reply_markup=main_keyboard()
        )
        return

    kb = []

    for order_id, title, first_name, last_name, _ in orders:
        client_str = f" ({first_name} {last_name or ''})".strip() if first_name else ""
        kb.append([
            InlineKeyboardButton(
                text=f"✅ №{order_id}: {title}{client_str}",
                callback_data=f"view_order_{order_id}"
            )
        ])

    await message.answer(
        "📁 **Виконані завдання:**\nОбери завдання для перегляду детальної інформації:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

# --- ДЕТАЛІ ЗАВДАННЯ ТА КНОПКИ ---

async def view_order_card_by_id(callback: types.CallbackQuery, order_id: int):
    order, items = await db.get_order_details(order_id, callback.from_user.id)

    if not order:
        await callback.message.edit_text("Завдання не знайдено або було видалено.")
        return

    _, title, status, first_name, last_name, phone, address = order

    client_full = f"{first_name or 'Без замовника'} {last_name or ''}".strip()
    text = f"📋 **Завдання №{order_id}:** {title}\n"
    text += f"👤 **Замовник:** {client_full}\n"

    if phone:
        text += f"📱 **Телефон:** {phone}\n"
    if address:
        text += f"🏠 **Адреса:** {address}\n\n"
    text += "<b>Складники кошторису:</b>\n"
    total_work = 0
    total_mat = 0

    for i, (item_type, name, unit, unit_price, quantity, total_price) in enumerate(items, 1):
        icon = "🛠" if item_type == "work" else "📦"
        cost = unit_price * quantity
        if item_type == "work":
            total_work += cost
        else:
            total_mat += cost
        text += f"{i}. {icon} {name} — {quantity} {unit} × {unit_price} грн = <b>{cost:.2f} грн</b>\n"

    text += f"\n💳 **Разом до сплати:** {total_work + total_mat:.2f} грн\n"
    text += f"📉 **Матеріали:** {total_mat:.2f} грн\n"
    text += f"💰 **Прибуток:** {total_work:.2f} грн\n"

    kb_rows = [
        [
            InlineKeyboardButton(text="✏️ Редагувати завдання", callback_data=f"edit_order_{order_id}")
        ],
    ]

    if status == "in_progress":
        kb_rows.append([
            InlineKeyboardButton(text="✅ Помітити як виконане", callback_data=f"confirm_complete_order_{order_id}")
        ])

    kb_rows.append([
        InlineKeyboardButton(text="🗑 Видалити завдання", callback_data=f"confirm_delete_order_{order_id}")
    ])

    back_callback = "back_to_orders" if status == "in_progress" else "back_to_completed_orders"
    kb_rows.append([
        InlineKeyboardButton(text="⬅️ Назад до списку", callback_data=back_callback)
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("view_order_"))
async def view_order_card(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    await view_order_card_by_id(callback, order_id)

@router.callback_query(F.data == "back_to_orders")
async def back_to_orders_handler(callback: types.CallbackQuery):
    orders = await db.get_user_orders(callback.from_user.id, status='in_progress')
    kb = []
    for order_id, title, first_name, last_name, _ in orders:
        client_str = f" ({first_name} {last_name or ''})".strip() if first_name else ""
        kb.append([
            InlineKeyboardButton(
                text=f"📌 №{order_id}: {title}{client_str}",
                callback_data=f"view_order_{order_id}"
            )
        ])

    await callback.message.edit_text(
        "⏳ **Завдання в роботі:**",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@router.callback_query(F.data == "back_to_completed_orders")
async def back_to_completed_orders_handler(callback: types.CallbackQuery):
    orders = await db.get_user_orders(callback.from_user.id, status='completed')
    kb = []
    for order_id, title, first_name, last_name, _ in orders:
        client_str = f" ({first_name} {last_name or ''})".strip() if first_name else ""
        kb.append([
            InlineKeyboardButton(
                text=f"✅ №{order_id}: {title}{client_str}",
                callback_data=f"view_order_{order_id}"
            )
        ])

    await callback.message.edit_text(
        "📁 **Виконані завдання:**",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

# --- ПІДТВЕРДЖЕННЯ ТА ВИДАЛЕННЯ ЗАВДАННЯ ---

@router.callback_query(F.data.startswith("confirm_delete_order_"))
async def confirm_delete_order_dialog(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ Так, видалити", callback_data=f"delete_order_now_{order_id}"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data=f"view_order_{order_id}")
        ]
    ])

    await callback.message.edit_text(
        "❓ **Ви дійсно бажаєте видалити це завдання?**\n(Всі позиції кошторису також будуть видалені)",
        parse_mode="Markdown",
        reply_markup=kb
    )

@router.callback_query(F.data.startswith("delete_order_now_"))
async def delete_order_action(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[3])

    order, _ = await db.get_order_details(order_id, callback.from_user.id)
    order_status = order[2] if order else "in_progress"

    success = await db.delete_order(order_id, callback.from_user.id)

    if success:
        await callback.answer("✅ Завдання успішно видалено!", show_alert=True)

        orders = await db.get_user_orders(callback.from_user.id, status=order_status)

        if order_status == "in_progress":
            empty_text = "📭 У вас більше немає активних завдань у роботі."
            list_title = "⏳ **Завдання в роботі:**"
            icon = "📌"
        else:
            empty_text = "📭 У вас більше немає виконаних завдань."
            list_title = "📁 **Виконані завдання:**"
            icon = "✅"

        if not orders:
            await callback.message.edit_text(empty_text)
            return

        kb = []

        for oid, title, first_name, last_name, _ in orders:
            client_str = f" ({first_name} {last_name or ''})".strip() if first_name else ""
            kb.append([
                InlineKeyboardButton(
                    text=f"{icon} №{oid}: {title}{client_str}",
                    callback_data=f"view_order_{oid}"
                )
            ])

        await callback.message.edit_text(
            list_title,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )

    else:
        await callback.answer("❌ Помилка під час видалення.", show_alert=True)


# --- ПОЗНАЧЕННЯ ЗАВДАННЯ ЯК ВИКОНАНОГО ---

@router.callback_query(F.data.startswith("confirm_complete_order_"))
async def confirm_complete_order_dialog(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Так, виконано", callback_data=f"complete_order_now_{order_id}"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data=f"view_order_{order_id}")
        ]
    ])

    await callback.message.edit_text(
        "❓ **Позначити це завдання як виконане?**\nВоно переміститься зі списку \"Завдання в роботі\" до \"Виконані завдання\".",
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.callback_query(F.data.startswith("complete_order_now_"))
async def complete_order_action(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    success = await db.complete_order(order_id, callback.from_user.id)

    if not success:
        await callback.answer("❌ Помилка. Можливо, завдання вже виконане або видалене.", show_alert=True)
        return

    await callback.answer("✅ Завдання позначено як виконане!", show_alert=True)

    # Повертаємось до списку завдань у роботі
    orders = await db.get_user_orders(callback.from_user.id, status='in_progress')
    if not orders:
        await callback.message.edit_text("📭 У вас більше немає активних завдань у роботі.")
        return

    kb = []
    for oid, title, first_name, last_name, _ in orders:
        client_str = f" ({first_name} {last_name or ''})".strip() if first_name else ""
        kb.append([
            InlineKeyboardButton(
                text=f"📌 №{oid}: {title}{client_str}",
                callback_data=f"view_order_{oid}"
            )
        ])

    await callback.message.edit_text(
        "⏳ **Завдання в роботі:**",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


# --- РЕДАГУВАННЯ ЗАВДАННЯ ---

class EditOrder(StatesGroup):
    menu = State()
    waiting_for_title = State()
    item_name = State()
    item_unit = State()
    item_price = State()
    item_quantity = State()


async def show_edit_menu(event: types.Message | types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    title = data.get("title", "")
    items = data.get("items", [])

    text = f"✏️ <b>Редагування завдання:</b> {title}\n\n"

    if not items:
        text += "<i>Позицій ще немає.</i>\n\n"
    else:
        text += "<b>Складники кошторису:</b>\n"
        total = 0
        for i, item in enumerate(items, 1):
            icon = "🛠" if item["item_type"] == "work" else "📦"
            cost = item["unit_price"] * item["quantity"]
            total += cost
            text += f"{i}. {icon} {item['name']} — {item['quantity']} {item['unit']} × {item['unit_price']} грн = <b>{cost:.2f} грн</b>\n"
        text += f"\n💳 <b>Разом:</b> {total:.2f} грн\n"

    kb_rows = []
    for i, item in enumerate(items):
        kb_rows.append([
            InlineKeyboardButton(text=f"🖊 {i + 1}. {item['name'][:20]}", callback_data=f"edit_item_{i}"),
            InlineKeyboardButton(text="🗑", callback_data=f"edit_del_item_{i}"),
        ])

    kb_rows.append([
        InlineKeyboardButton(text="➕ Додати роботу", callback_data="edit_add_type_work"),
        InlineKeyboardButton(text="📦 Додати матеріал", callback_data="edit_add_type_material"),
    ])
    kb_rows.append([
        InlineKeyboardButton(text="✏️ Змінити назву", callback_data="edit_change_title"),
    ])
    kb_rows.append([
        InlineKeyboardButton(text="✅ Зберегти зміни", callback_data="edit_save"),
        InlineKeyboardButton(text="❌ Відмінити зміни", callback_data="edit_cancel"),
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("edit_order_"))
async def start_edit_order(callback: types.CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    order, items_raw = await db.get_order_details(order_id, callback.from_user.id)

    if not order:
        await callback.answer("Завдання не знайдено.", show_alert=True)
        return

    items = [
        {
            "item_type": item_type,
            "name": name,
            "unit": unit,
            "unit_price": unit_price,
            "quantity": quantity,
        }
        for item_type, name, unit, unit_price, quantity, _ in items_raw
    ]

    await state.update_data(edit_order_id=order_id, title=order[1], items=items, editing_index=None)
    await state.set_state(EditOrder.menu)
    await show_edit_menu(callback, state)


@router.callback_query(EditOrder.menu, F.data == "edit_change_title")
async def edit_change_title_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditOrder.waiting_for_title)
    await callback.message.answer(
        "📝 Введи нову назву завдання:",
        reply_markup=cancel_kb(show_skip=False),
    )


@router.message(EditOrder.waiting_for_title)
async def edit_change_title_process(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(EditOrder.menu)
    await show_edit_menu(message, state)


@router.callback_query(EditOrder.menu, F.data.startswith("edit_add_type_"))
async def edit_start_add_item(callback: types.CallbackQuery, state: FSMContext):
    item_type = callback.data.split("_")[3]
    await state.update_data(current_item_type=item_type, editing_index=None)
    await state.set_state(EditOrder.item_name)
    type_str = "роботи" if item_type == "work" else "матеріалу"
    await callback.message.answer(
        f"🔹 Введи назву {type_str}:",
        reply_markup=cancel_kb(show_skip=False),
    )


@router.callback_query(EditOrder.menu, F.data.startswith("edit_item_"))
async def edit_start_edit_item(callback: types.CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    items = data.get("items", [])

    if index >= len(items):
        await callback.answer("Позицію не знайдено.", show_alert=True)
        return

    item = items[index]
    await state.update_data(current_item_type=item["item_type"], editing_index=index)
    await state.set_state(EditOrder.item_name)
    type_str = "роботи" if item["item_type"] == "work" else "матеріалу"
    await callback.message.answer(
        f"🔹 Поточна назва: <b>{item['name']}</b>\nВведи нову назву {type_str} (або надішли ту саму):",
        parse_mode="HTML",
        reply_markup=cancel_kb(show_skip=False),
    )


@router.callback_query(EditOrder.menu, F.data.startswith("edit_del_item_"))
async def edit_delete_item(callback: types.CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[3])
    data = await state.get_data()
    items = data.get("items", [])

    if index >= len(items):
        await callback.answer("Позицію не знайдено.", show_alert=True)
        return

    items.pop(index)
    await state.update_data(items=items)
    await callback.answer("🗑 Позицію видалено (не забудь зберегти зміни).")
    await show_edit_menu(callback, state)


@router.message(EditOrder.item_name)
async def edit_process_item_name(message: types.Message, state: FSMContext):
    await state.update_data(current_item_name=message.text.strip())
    await state.set_state(EditOrder.item_unit)
    units_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="шт"), KeyboardButton(text="год"), KeyboardButton(text="послуга")],
            [KeyboardButton(text="м²"), KeyboardButton(text="комплект")],
            [KeyboardButton(text="❌ Скасувати")],
        ],
        resize_keyboard=True,
    )
    await message.answer("📐 Вкажи одиницю виміру:", reply_markup=units_kb)


@router.message(EditOrder.item_unit)
async def edit_process_item_unit(message: types.Message, state: FSMContext):
    await state.update_data(current_item_unit=message.text.strip())
    await state.set_state(EditOrder.item_price)
    await message.answer("💰 Вкажи ціну за одиницю (у грн):", reply_markup=cancel_kb(show_skip=False))


@router.message(EditOrder.item_price)
async def edit_process_item_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        await state.update_data(current_item_price=price)
        await state.set_state(EditOrder.item_quantity)
        await message.answer("🔢 Вкажи кількість:", reply_markup=cancel_kb(show_skip=False))
    except ValueError:
        await message.answer("❌ Будь ласка, введи число! Спробуй ще раз:")


@router.message(EditOrder.item_quantity)
async def edit_process_item_quantity(message: types.Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
        data = await state.get_data()
        new_item = {
            "item_type": data["current_item_type"],
            "name": data["current_item_name"],
            "unit": data["current_item_unit"],
            "unit_price": data["current_item_price"],
            "quantity": qty,
        }
        items = data.get("items", [])
        editing_index = data.get("editing_index")

        if editing_index is None:
            items.append(new_item)
        else:
            items[editing_index] = new_item

        await state.update_data(items=items, editing_index=None)
        await state.set_state(EditOrder.menu)
        await show_edit_menu(message, state)

    except ValueError:
        await message.answer("❌ Будь ласка, введи число! Спробуй ще раз:")


@router.callback_query(EditOrder.menu, F.data == "edit_save")
async def edit_save_order(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data["edit_order_id"]
    title = data["title"]
    items = data.get("items", [])

    if not items:
        await callback.answer("⚠️ У завданні має бути хоча б одна позиція!", show_alert=True)
        return

    success = await db.update_order(order_id, callback.from_user.id, title, items)
    await state.clear()

    if not success:
        await callback.answer("❌ Помилка збереження.", show_alert=True)
        return

    await callback.answer("✅ Зміни збережено!", show_alert=True)
    await view_order_card_by_id(callback, order_id)
    await callback.message.answer("🚀 Продовжуємо роботу", reply_markup=main_keyboard())


@router.callback_query(EditOrder.menu, F.data == "edit_cancel")
async def edit_cancel_order(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("edit_order_id")
    await state.clear()
    await callback.answer("Зміни скасовано.")
    await view_order_card_by_id(callback, order_id)
    await callback.message.answer("🚀 Продовжуємо роботу", reply_markup=main_keyboard())


# --- СТАТИСТИКА ---

class Stats(StatesGroup):
    picking_range = State()


MONTH_NAMES_UA = {
    1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень",
    5: "Травень", 6: "Червень", 7: "Липень", 8: "Серпень",
    9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень",
}


def get_last_complete_week():
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)
    return last_monday, last_sunday


def get_last_complete_month():
    today = date.today()
    first_of_this_month = today.replace(day=1)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    first_day_prev_month = last_day_prev_month.replace(day=1)
    return first_day_prev_month, last_day_prev_month


def get_last_complete_quarter():
    today = date.today()
    current_q_first_month = (today.month - 1) // 3 * 3 + 1
    first_day_this_quarter = date(today.year, current_q_first_month, 1)
    last_day_prev_quarter = first_day_this_quarter - timedelta(days=1)
    prev_q_first_month = (last_day_prev_quarter.month - 1) // 3 * 3 + 1
    first_day_prev_quarter = date(last_day_prev_quarter.year, prev_q_first_month, 1)
    return first_day_prev_quarter, last_day_prev_quarter


def get_last_complete_year():
    last_year = date.today().year - 1
    return date(last_year, 1, 1), date(last_year, 12, 31)


PERIOD_META = {
    "week": ("тиждень", get_last_complete_week, 7),
    "month": ("місяць", get_last_complete_month, 30),
    "quarter": ("квартал", get_last_complete_quarter, 90),
    "year": ("рік", get_last_complete_year, 365),
}


def build_stats_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Тиждень", callback_data="stats_period_week"),
            InlineKeyboardButton(text="📅 Місяць", callback_data="stats_period_month"),
        ],
        [
            InlineKeyboardButton(text="📅 Квартал", callback_data="stats_period_quarter"),
            InlineKeyboardButton(text="📅 Рік", callback_data="stats_period_year"),
        ],
        [InlineKeyboardButton(text="📊 Весь період", callback_data="stats_period_all")],
        [InlineKeyboardButton(text="🗓 Обрати діапазон", callback_data="stats_range_start")],
    ])


@router.message(F.text == "📊 Статистика")
async def show_statistics_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📊 **Статистика**\nОбери період:",
        parse_mode="Markdown",
        reply_markup=build_stats_menu_kb(),
    )


@router.callback_query(F.data == "stats_menu")
async def stats_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📊 **Статистика**\nОбери період:",
        parse_mode="Markdown",
        reply_markup=build_stats_menu_kb(),
    )


async def render_and_show_stats(callback: types.CallbackQuery, date_from, date_to, label: str):
    user_id = callback.from_user.id
    date_from_str = f"{date_from} 00:00:00" if date_from else None
    date_to_str = f"{date_to} 23:59:59" if date_to else None
    stats = await db.get_statistics(user_id, date_from_str, date_to_str)

    text = f"📊 **Статистика за {label}**\n\n"
    text += f"💰 Чистий дохід: {stats['total_work']:.2f} грн\n"
    text += f"✅ Виконано завдань: {stats['order_count']}\n"
    text += f"📉 Витрати на матеріали: {stats['total_mat']:.2f} грн\n"

    if stats["top_client"]:
        text += f"🏆 Топ-замовник: {stats['top_client']} ({stats['top_client_revenue']:.2f} грн)\n"
    else:
        text += "🏆 Топ-замовник: —\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Інший період", callback_data="stats_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "stats_period_all")
async def stats_period_all(callback: types.CallbackQuery):
    await render_and_show_stats(callback, None, None, "весь період")


@router.callback_query(F.data.in_([f"stats_period_{p}" for p in PERIOD_META]))
async def stats_period_submenu(callback: types.CallbackQuery):
    period = callback.data.split("_")[2]
    label, _, rolling_days = PERIOD_META[period]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📆 Останній повний {label}", callback_data=f"stats_full_{period}")],
        [InlineKeyboardButton(text=f"🔄 Останні {rolling_days} днів", callback_data=f"stats_rolling_{period}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="stats_menu")],
    ])
    await callback.message.edit_text(
        f"📊 Період: **{label}**\nОбери варіант розрахунку:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("stats_full_"))
async def stats_full_period(callback: types.CallbackQuery):
    period = callback.data.split("_")[2]
    label, full_func, _ = PERIOD_META[period]
    date_from, date_to = full_func()
    range_str = f"{date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')}"
    await render_and_show_stats(callback, date_from, date_to, f"останній повний {label} ({range_str})")


@router.callback_query(F.data.startswith("stats_rolling_"))
async def stats_rolling_period(callback: types.CallbackQuery):
    period = callback.data.split("_")[2]
    label, _, rolling_days = PERIOD_META[period]
    date_to = date.today()
    date_from = date_to - timedelta(days=rolling_days - 1)
    range_str = f"{date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')}"
    await render_and_show_stats(callback, date_from, date_to, f"останні {rolling_days} днів ({range_str})")


# --- ВИБІР ДІАПАЗОНУ ЧЕРЕЗ КАЛЕНДАР ---

def build_calendar_kb(year: int, month: int, min_date: date, max_date: date):
    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]

    header = [
        InlineKeyboardButton(text="‹", callback_data=f"cal_nav_prev_{year}_{month}"),
        InlineKeyboardButton(text=f"{MONTH_NAMES_UA[month]} {year}", callback_data="cal_noop"),
        InlineKeyboardButton(text="›", callback_data=f"cal_nav_next_{year}_{month}"),
    ]
    weekday_row = [InlineKeyboardButton(text=d, callback_data="cal_noop") for d in weekday_names]
    rows = [header, weekday_row]

    first_weekday, days_in_month = pycalendar.monthrange(year, month)
    row = [InlineKeyboardButton(text=" ", callback_data="cal_noop") for _ in range(first_weekday)]

    for day in range(1, days_in_month + 1):
        current = date(year, month, day)
        if current < min_date or current > max_date:
            row.append(InlineKeyboardButton(text=f"·{day}·", callback_data="cal_noop"))
        else:
            row.append(InlineKeyboardButton(text=str(day), callback_data=f"cal_day_{year}_{month}_{day}"))
        if len(row) == 7:
            rows.append(row)
            row = []

    if row:
        row += [InlineKeyboardButton(text=" ", callback_data="cal_noop") for _ in range(7 - len(row))]
        rows.append(row)

    rows.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="stats_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_calendar(callback: types.CallbackQuery, state: FSMContext, year: int, month: int):
    data = await state.get_data()
    min_date = date.fromisoformat(data["cal_min"])
    max_date = date.fromisoformat(data["cal_max"])
    picking = data.get("cal_picking", "from")
    prompt = "Обери дату початку періоду:" if picking == "from" else "Обери дату кінця періоду:"

    kb = build_calendar_kb(year, month, min_date, max_date)
    await callback.message.edit_text(f"🗓 **{prompt}**", parse_mode="Markdown", reply_markup=kb)
    await state.update_data(cal_year=year, cal_month=month)


@router.callback_query(F.data == "stats_range_start")
async def stats_range_start(callback: types.CallbackQuery, state: FSMContext):
    reg_date_str = await db.get_user_registration_date(callback.from_user.id)
    today = date.today()
    min_date = date.fromisoformat(reg_date_str) if reg_date_str else today

    await state.set_state(Stats.picking_range)
    await state.update_data(cal_min=min_date.isoformat(), cal_max=today.isoformat(), cal_picking="from")
    await show_calendar(callback, state, today.year, today.month)


@router.callback_query(F.data == "cal_noop")
async def cal_noop_handler(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("cal_nav_"))
async def cal_nav_handler(callback: types.CallbackQuery, state: FSMContext):
    _, _, direction, year, month = callback.data.split("_")
    year, month = int(year), int(month)

    if direction == "prev":
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    else:
        month += 1
        if month == 13:
            month, year = 1, year + 1

    await show_calendar(callback, state, year, month)


@router.callback_query(F.data.startswith("cal_day_"))
async def cal_day_handler(callback: types.CallbackQuery, state: FSMContext):
    _, _, year, month, day = callback.data.split("_")
    selected = date(int(year), int(month), int(day))

    data = await state.get_data()
    min_date = date.fromisoformat(data["cal_min"])
    max_date = date.fromisoformat(data["cal_max"])

    if selected < min_date or selected > max_date:
        await callback.answer("❌ Дата поза допустимим діапазоном.", show_alert=True)
        return

    picking = data.get("cal_picking", "from")

    if picking == "from":
        await state.update_data(
            cal_date_from=selected.isoformat(),
            cal_picking="to",
            cal_min=selected.isoformat(),
        )
        await callback.answer(f"Початок: {selected.strftime('%d.%m.%Y')}")
        await show_calendar(callback, state, selected.year, selected.month)
    else:
        date_from = date.fromisoformat(data["cal_date_from"])
        date_to = selected
        await state.clear()
        label = f"{date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')}"
        await render_and_show_stats(callback, date_from, date_to, label)