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

@router.message(F.text == "➕ Нове завдання")

async def start_new_order(message: types.Message, state: FSMContext):
    clients = await db.get_user_clients(message.from_user.id)
    kb = []
    for client_id, first_name, last_name, phone in clients:
        full_name = f"{first_name} {last_name or ''}".strip()
        kb.append(
            [
                InlineKeyboardButton(
                    text=f"👤 {full_name} ({phone})",
                    callback_data=f"select_client_{client_id}",
                )
            ]
        )

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

    await state.set_state(CreateOrder.selecting_client)
    await message.answer(
        "👤 **Обери замовника зі списку або додай нового:**",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
    )

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

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Редагувати завдання", callback_data=f"edit_order_{order_id}")
        ],
        [
            InlineKeyboardButton(text="🗑 Видалити завдання", callback_data=f"confirm_delete_order_{order_id}")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад до списку", callback_data="back_to_orders")
        ]
    ])

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
    success = await db.delete_order(order_id, callback.from_user.id)

    if success:
        await callback.answer("✅ Завдання успішно видалено!", show_alert=True)
        # Повертаємось до списку завдань
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

    else:
        await callback.answer("❌ Помилка під час видалення.", show_alert=True)


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