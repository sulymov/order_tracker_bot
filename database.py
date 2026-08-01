import aiosqlite

DB_NAME = "tracker.db"

async def init_db():
    """Створення всіх необхідних таблиць згідно з ТЗ"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        # 1. Таблиця користувачів

        await db.execute(

            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                role TEXT DEFAULT 'user',
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 2. Таблиця замовників

        await db.execute(

            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT,
                phone TEXT NOT NULL,
                address TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            """
        )

        # 3. Таблиця замовлень

        await db.execute(

            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'in_progress',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
            """
        )

        # 4. Таблиця позицій (роботи та матеріали)

        await db.execute(

            """
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                name TEXT NOT NULL,
                unit TEXT NOT NULL,
                unit_price REAL NOT NULL,
                quantity REAL NOT NULL,
                total_price REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE
            )
            """
        )

        await db.commit()

async def get_or_create_user(
    user_id: int, username: str, first_name: str, admin_id: int
):

    """Отримання або реєстрація користувача з перевіркою прав Адміна"""

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, role, status FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()
            if user:
                return user

        role = "admin" if user_id == admin_id else "user"
        status = "active" if user_id == admin_id else "pending"

        await db.execute(

            """
            INSERT INTO users (user_id, username, first_name, role, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, username, first_name, role, status),
        )

        await db.commit()
        return (user_id, role, status)

# --- ФУНКЦІЇ ДЛЯ КЛІЄНТІВ ТА ЗАМОВЛЕНЬ ---

async def add_client(
    user_id: int,
    first_name: str,
    phone: str,
    last_name: str = None,
    address: str = None,
):

    """Створення нового замовника"""

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(

            """
            INSERT INTO clients (user_id, first_name, last_name, phone, address)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, first_name, last_name, phone, address),
        )
        await db.commit()
        return cursor.lastrowid


async def get_user_clients(user_id: int):

    """Отримання списку клієнтів користувача"""

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, first_name, last_name, phone FROM clients WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            return await cursor.fetchall()


async def create_order(user_id: int, client_id: int, title: str, items: list):

    """Створення замовлення разом із його складниками"""

    async with aiosqlite.connect(DB_NAME) as db:

        # Вставляємо основний запис замовлення

        cursor = await db.execute(

            """
            INSERT INTO orders (user_id, client_id, title, status)
            VALUES (?, ?, ?, 'in_progress')
            """,
            (user_id, client_id, title),
        )
        order_id = cursor.lastrowid

        # Формуємо список позицій (робіт та матеріалів)

        items_data = [

            (
                order_id,
                item["item_type"],
                item["name"],
                item["unit"],
                item["unit_price"],
                item["quantity"],
                item["unit_price"] * item["quantity"],
            )

            for item in items

        ]

        # Пакетно додаємо всі позиції

        await db.executemany(

            """
            INSERT INTO order_items (order_id, item_type, name, unit, unit_price, quantity, total_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            items_data,
        )

        # Фіксуємо зміни (транзакцію)

        await db.commit()
        return order_id


async def get_user_orders(user_id: int, status: str = "in_progress"):

    async with aiosqlite.connect(DB_NAME) as db:

        async with db.execute(

            """
            SELECT o.id, o.title, c.first_name, c.last_name, o.created_at
            FROM orders o
            LEFT JOIN clients c ON o.client_id = c.id
            WHERE o.user_id = ? AND o.status = ?
            ORDER BY o.id DESC
            """,
            (user_id, status),
        ) as cursor:
            return await cursor.fetchall()

async def get_order_details(order_id: int, user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(

            """
            SELECT o.id, o.title, o.status, c.first_name, c.last_name, c.phone, c.address
            FROM orders o
            LEFT JOIN clients c ON o.client_id = c.id
            WHERE o.id = ? AND o.user_id = ?
            """,
            (order_id, user_id),
        ) as cursor:
            order = await cursor.fetchone()

        if not order:
            return None, []

        async with db.execute(

            """
            SELECT item_type, name, unit, unit_price, quantity, total_price
            FROM order_items
            WHERE order_id = ?
            """,
            (order_id,),
        ) as cursor:
            items = await cursor.fetchall()
        return order, items


async def delete_order(order_id: int, user_id: int) -> bool:

    async with aiosqlite.connect(DB_NAME) as db:

        # Вмикаємо підтримку Foreign Keys для поточного з'єднання

        await db.execute("PRAGMA foreign_keys = ON;")

        # Видаляємо замовлення (всі order_items видаляться автоматично)

        cursor = await db.execute(
            "DELETE FROM orders WHERE id = ? AND user_id = ?",
            (order_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0 
    
async def update_order(order_id: int, user_id: int, title: str, items: list) -> bool:
    """Оновлення назви та повного списку позицій завдання (перезапис)"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        cursor = await db.execute(
            "UPDATE orders SET title = ? WHERE id = ? AND user_id = ?",
            (title, order_id, user_id),
        )

        if cursor.rowcount == 0:
            return False

        await db.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))

        items_data = [
            (
                order_id,
                item["item_type"],
                item["name"],
                item["unit"],
                item["unit_price"],
                item["quantity"],
                item["unit_price"] * item["quantity"],
            )
            for item in items
        ]

        await db.executemany(
            """
            INSERT INTO order_items (order_id, item_type, name, unit, unit_price, quantity, total_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            items_data,
        )

        await db.commit()
        return True