import aiosqlite
import csv
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List
from models import User, Venue, Service, Order, VIPClient, Song
import config
from utils import get_stats_date

class Database:
    _conn = None

    def __init__(self, db_path: str = config.DATABASE_PATH):
        self.db_path = db_path

    @asynccontextmanager
    async def _get_db(self):
        if Database._conn is None:
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA busy_timeout=5000")
            Database._conn = conn
        yield Database._conn

    def get_db(self):
        return self._get_db()

    async def close(self):
        if Database._conn is not None:
            await Database._conn.close()
            Database._conn = None

    async def init_db(self):
        async with self._get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT NOT NULL,
                    role INTEGER NOT NULL,
                    venue_id INTEGER,
                    table_number INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_blocked BOOLEAN DEFAULT 0,
                    language TEXT DEFAULT 'ru',
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS venues (
                    venue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    city TEXT NOT NULL,
                    owner_phone TEXT,
                    owner_email TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    table_count INTEGER DEFAULT 12,
                    songs_per_table INTEGER DEFAULT 2,
                    table_mode TEXT DEFAULT 'sequential',
                    chat_enabled BOOLEAN DEFAULT 0,
                    chat_link TEXT,
                    vip_description TEXT,
                    vip_description_ro TEXT,
                    vip_cashback REAL DEFAULT 0
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS services (
                    service_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    price REAL NOT NULL,
                    is_free BOOLEAN DEFAULT 0,
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER NOT NULL,
                    table_number INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    service_id INTEGER NOT NULL,
                    song_name TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    position INTEGER DEFAULT 0,
                    is_next INTEGER DEFAULT 0,
                    marked_next_at TIMESTAMP,
                    started_at TIMESTAMP,
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (service_id) REFERENCES services(service_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS vip_clients (
                    user_id INTEGER NOT NULL,
                    venue_id INTEGER NOT NULL,
                    balance REAL DEFAULT 0,
                    cashback_percent REAL DEFAULT 0,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, venue_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS songs (
                    song_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER NOT NULL,
                    artist TEXT NOT NULL,
                    title TEXT NOT NULL,
                    code TEXT,
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER NOT NULL,
                    user_id INTEGER,
                    order_id INTEGER,
                    amount REAL NOT NULL,
                    type TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (order_id) REFERENCES orders(order_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    favorite_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    venue_id INTEGER NOT NULL,
                    song_id INTEGER NOT NULL,
                    service_id INTEGER NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
                    FOREIGN KEY (song_id) REFERENCES songs(song_id),
                    FOREIGN KEY (service_id) REFERENCES services(service_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER NOT NULL,
                    from_user_id INTEGER NOT NULL,
                    to_user_id INTEGER NOT NULL,
                    message_text TEXT NOT NULL,
                    table_number INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_read BOOLEAN DEFAULT 0,
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
                    FOREIGN KEY (from_user_id) REFERENCES users(user_id),
                    FOREIGN KEY (to_user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    table_number INTEGER NOT NULL,
                    request_type TEXT NOT NULL,
                    amount REAL DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS table_groups (
                    venue_id INTEGER NOT NULL,
                    table_number INTEGER NOT NULL,
                    admin_user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (venue_id, table_number),
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
                    FOREIGN KEY (admin_user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS table_join_requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER NOT NULL,
                    table_number INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_log (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER,
                    user_id INTEGER,
                    event_type TEXT NOT NULL,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    total_orders INTEGER DEFAULT 0,
                    completed_orders INTEGER DEFAULT 0,
                    cancelled_orders INTEGER DEFAULT 0,
                    total_revenue REAL DEFAULT 0,
                    vip_revenue REAL DEFAULT 0,
                    regular_revenue REAL DEFAULT 0,
                    unique_users INTEGER DEFAULT 0,
                    new_users INTEGER DEFAULT 0,
                    total_topups REAL DEFAULT 0,
                    total_cashback REAL DEFAULT 0,
                    total_songs_played INTEGER DEFAULT 0,
                    avg_wait_time REAL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(venue_id, date),
                    FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
                )
            """)

            try:
                cursor = await db.execute("PRAGMA table_info(users)")
                columns = await cursor.fetchall()
                has_table_number = any(col[1] == 'table_number' for col in columns)
                
                if not has_table_number:
                    await db.execute("ALTER TABLE users ADD COLUMN table_number INTEGER")
                    print("✅ Migration: Added table_number column to users table")
                
                cursor = await db.execute("PRAGMA table_info(orders)")
                columns = await cursor.fetchall()
                has_artist_name = any(col[1] == 'artist_name' for col in columns)
                has_song_id = any(col[1] == 'song_id' for col in columns)
                
                if not has_artist_name:
                    await db.execute("ALTER TABLE orders ADD COLUMN artist_name TEXT")
                    print("✅ Migration: Added artist_name column to orders table")
                
                if not has_song_id:
                    await db.execute("ALTER TABLE orders ADD COLUMN song_id INTEGER")
                    print("✅ Migration: Added song_id column to orders table")
                
                cursor = await db.execute("PRAGMA table_info(requests)")
                columns = await cursor.fetchall()
                has_amount = any(col[1] == 'amount' for col in columns)
                
                if not has_amount:
                    await db.execute("ALTER TABLE requests ADD COLUMN amount REAL DEFAULT 0")
                    print("✅ Migration: Added amount column to requests table")

                cursor = await db.execute("PRAGMA table_info(orders)")
                columns = await cursor.fetchall()
                has_is_next = any(col[1] == 'is_next' for col in columns)
                has_marked_next_at = any(col[1] == 'marked_next_at' for col in columns)

                if not has_is_next:
                    await db.execute("ALTER TABLE orders ADD COLUMN is_next INTEGER DEFAULT 0")
                    print("✅ Migration: Added is_next column to orders table")

                if not has_marked_next_at:
                    await db.execute("ALTER TABLE orders ADD COLUMN marked_next_at TIMESTAMP")
                    print("✅ Migration: Added marked_next_at column to orders table")

                has_started_at = any(col[1] == 'started_at' for col in columns)
                if not has_started_at:
                    await db.execute("ALTER TABLE orders ADD COLUMN started_at TIMESTAMP")
                    print("✅ Migration: Added started_at column to orders table")

                has_cancelled_at = any(col[1] == 'cancelled_at' for col in columns)
                if not has_cancelled_at:
                    await db.execute("ALTER TABLE orders ADD COLUMN cancelled_at TIMESTAMP")
                    print("✅ Migration: Added cancelled_at column to orders table")

                cursor = await db.execute("PRAGMA table_info(venues)")
                columns = await cursor.fetchall()
                has_vip_cashback = any(col[1] == 'vip_cashback' for col in columns)

                if not has_vip_cashback:
                    await db.execute("ALTER TABLE venues ADD COLUMN vip_cashback REAL DEFAULT 0")
                    print("✅ Migration: Added vip_cashback column to venues table")

                has_vip_description_ro = any(col[1] == 'vip_description_ro' for col in columns)
                if not has_vip_description_ro:
                    await db.execute("ALTER TABLE venues ADD COLUMN vip_description_ro TEXT")
                    print("✅ Migration: Added vip_description_ro column to venues table")

                cursor2 = await db.execute("PRAGMA table_info(users)")
                user_cols = await cursor2.fetchall()
                has_language = any(col[1] == 'language' for col in user_cols)
                if not has_language:
                    await db.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'ru'")
                    print("✅ Migration: Added language column to users table")
            except Exception as e:
                print(f"⚠️ Migration error (may be safe to ignore if column exists): {e}")

            await db.commit()

    async def get_user(self, user_id: int) -> Optional[User]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return User(**dict(row))
        return None

    async def get_user_language(self, user_id: int) -> str:
        async with self._get_db() as db:
            async with db.execute(
                "SELECT language FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    return row[0]
        return 'ru'

    async def set_user_language(self, user_id: int, language: str):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE users SET language = ? WHERE user_id = ?",
                (language, user_id)
            )
            await db.commit()

    async def get_user_by_username(self, username: str) -> Optional[User]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return User(**dict(row))
        return None

    async def create_user(self, user_id: int, username: Optional[str], 
                         first_name: str, role: int, venue_id: Optional[int] = None):
        async with self._get_db() as db:
            await db.execute(
                """INSERT INTO users (user_id, username, first_name, role, venue_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, username, first_name, role, venue_id)
            )
            await db.commit()

    async def update_user_role(self, user_id: int, role: int, venue_id: Optional[int] = None):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE users SET role = ?, venue_id = ? WHERE user_id = ?",
                (role, venue_id, user_id)
            )
            await db.commit()

    async def update_user_venue(self, user_id: int, venue_id: int):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE users SET venue_id = ? WHERE user_id = ?",
                (venue_id, user_id)
            )
            await db.commit()

    async def unbind_user_table(self, user_id: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT venue_id, table_number FROM users WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()

            await db.execute(
                "UPDATE users SET table_number = NULL WHERE user_id = ?",
                (user_id,)
            )

            if row and row["venue_id"] and row["table_number"]:
                venue_id = row["venue_id"]
                table_number = row["table_number"]
                async with db.execute(
                    "SELECT admin_user_id FROM table_groups WHERE venue_id = ? AND table_number = ?",
                    (venue_id, table_number)
                ) as cursor:
                    admin_row = await cursor.fetchone()

                if admin_row and admin_row["admin_user_id"] == user_id:
                    async with db.execute(
                        "SELECT user_id FROM users WHERE venue_id = ? AND table_number = ? ORDER BY created_at ASC LIMIT 1",
                        (venue_id, table_number)
                    ) as cursor:
                        new_admin = await cursor.fetchone()

                    if new_admin:
                        await db.execute(
                            "UPDATE table_groups SET admin_user_id = ? WHERE venue_id = ? AND table_number = ?",
                            (new_admin["user_id"], venue_id, table_number)
                        )
                    else:
                        await db.execute(
                            "DELETE FROM table_groups WHERE venue_id = ? AND table_number = ?",
                            (venue_id, table_number)
                        )

            await db.commit()

    async def unbind_user_venue(self, user_id: int):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE users SET venue_id = NULL, table_number = NULL WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()

    async def unbind_all_tables(self, venue_id: int):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE users SET table_number = NULL WHERE venue_id = ?",
                (venue_id,)
            )
            await db.execute(
                "DELETE FROM table_groups WHERE venue_id = ?",
                (venue_id,)
            )
            await db.execute(
                "DELETE FROM table_join_requests WHERE venue_id = ?",
                (venue_id,)
            )
            await db.commit()

    async def unbind_table(self, venue_id: int, table_number: int):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE users SET table_number = NULL WHERE venue_id = ? AND table_number = ?",
                (venue_id, table_number)
            )
            await db.execute(
                "DELETE FROM table_groups WHERE venue_id = ? AND table_number = ?",
                (venue_id, table_number)
            )
            await db.execute(
                "DELETE FROM table_join_requests WHERE venue_id = ? AND table_number = ?",
                (venue_id, table_number)
            )
            await db.commit()

    async def unbind_all_venue_users(self, venue_id: int):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE users SET venue_id = NULL, table_number = NULL WHERE venue_id = ?",
                (venue_id,)
            )
            await db.commit()

    async def reset_venue_roles(self, venue_id: int) -> list[int]:
        async with self._get_db() as db:
            async with db.execute(
                "SELECT user_id FROM users WHERE venue_id = ? AND role NOT IN (1, 2)",
                (venue_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                user_ids = [row[0] for row in rows]
            if user_ids:
                await db.execute(
                    "UPDATE users SET role = 0 WHERE venue_id = ? AND role NOT IN (1, 2)",
                    (venue_id,)
                )
                await db.commit()
            return user_ids

    async def get_all_users_count(self) -> int:
        async with self._get_db() as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def block_user(self, user_id: int, blocked: bool = True):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE users SET is_blocked = ? WHERE user_id = ?",
                (blocked, user_id)
            )
            await db.commit()

    async def get_table_users(self, venue_id: int, table_number: int) -> List[User]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE venue_id = ? AND table_number = ?",
                (venue_id, table_number)
            ) as cursor:
                rows = await cursor.fetchall()
                return [User(**dict(row)) for row in rows]

    async def get_table_users_count(self, venue_id: int, table_number: int) -> int:
        async with self._get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE venue_id = ? AND table_number = ?",
                (venue_id, table_number)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_table_admin_user_id(self, venue_id: int, table_number: int) -> Optional[int]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT admin_user_id FROM table_groups WHERE venue_id = ? AND table_number = ?",
                (venue_id, table_number)
            ) as cursor:
                row = await cursor.fetchone()
                return row["admin_user_id"] if row else None

    async def set_table_admin(self, venue_id: int, table_number: int, admin_user_id: int):
        async with self._get_db() as db:
            await db.execute(
                """INSERT OR REPLACE INTO table_groups (venue_id, table_number, admin_user_id)
                   VALUES (?, ?, ?)""",
                (venue_id, table_number, admin_user_id)
            )
            await db.commit()

    async def clear_table_admin(self, venue_id: int, table_number: int):
        async with self._get_db() as db:
            await db.execute(
                "DELETE FROM table_groups WHERE venue_id = ? AND table_number = ?",
                (venue_id, table_number)
            )
            await db.commit()

    async def create_table_join_request(self, venue_id: int, table_number: int, user_id: int) -> int:
        async with self._get_db() as db:
            cursor = await db.execute(
                """INSERT INTO table_join_requests (venue_id, table_number, user_id)
                   VALUES (?, ?, ?)""",
                (venue_id, table_number, user_id)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_table_join_request(self, request_id: int) -> Optional[dict]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM table_join_requests WHERE request_id = ?",
                (request_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_table_join_request_status(self, request_id: int, status: str):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE table_join_requests SET status = ? WHERE request_id = ?",
                (status, request_id)
            )
            await db.commit()

    async def has_pending_table_join_request(self, venue_id: int, table_number: int, user_id: int) -> bool:
        async with self._get_db() as db:
            async with db.execute(
                """SELECT 1 FROM table_join_requests
                   WHERE venue_id = ? AND table_number = ? AND user_id = ? AND status = 'pending'""",
                (venue_id, table_number, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                return bool(row)

    async def get_pending_table_join_request_id(self, venue_id: int, table_number: int, user_id: int) -> Optional[int]:
        async with self._get_db() as db:
            async with db.execute(
                """SELECT request_id FROM table_join_requests
                   WHERE venue_id = ? AND table_number = ? AND user_id = ? AND status = 'pending'
                   ORDER BY request_id DESC LIMIT 1""",
                (venue_id, table_number, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def create_venue(self, name: str, city: str, owner_phone: str, 
                          owner_email: str) -> int:
        async with self._get_db() as db:
            cursor = await db.execute(
                """INSERT INTO venues (name, city, owner_phone, owner_email)
                   VALUES (?, ?, ?, ?)""",
                (name, city, owner_phone, owner_email)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_venue(self, venue_id: int) -> Optional[Venue]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM venues WHERE venue_id = ?", (venue_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Venue(**dict(row))
        return None

    async def get_all_venues(self) -> List[Venue]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM venues") as cursor:
                rows = await cursor.fetchall()
                return [Venue(**dict(row)) for row in rows]

    async def update_venue_status(self, venue_id: int, is_active: bool):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE venues SET is_active = ? WHERE venue_id = ?",
                (is_active, venue_id)
            )
            await db.commit()

    async def delete_venue(self, venue_id: int):
        async with self._get_db() as db:
            await db.execute("DELETE FROM venues WHERE venue_id = ?", (venue_id,))
            await db.commit()

    async def update_venue_settings(self, venue_id: int, **kwargs):
        async with self._get_db() as db:
            set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            values = list(kwargs.values()) + [venue_id]
            await db.execute(
                f"UPDATE venues SET {set_clause} WHERE venue_id = ?",
                values
            )
            await db.commit()

    async def update_venue_cashback(self, venue_id: int, cashback: float):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE venues SET vip_cashback = ? WHERE venue_id = ?",
                (cashback, venue_id)
            )
            await db.commit()

    async def update_venue_vip_description(self, venue_id: int, description: str):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE venues SET vip_description = ? WHERE venue_id = ?",
                (description, venue_id)
            )
            await db.commit()

    async def update_venue_vip_description_ro(self, venue_id: int, description: str):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE venues SET vip_description_ro = ? WHERE venue_id = ?",
                (description, venue_id)
            )
            await db.commit()

    async def create_service(self, venue_id: int, name: str, 
                            description: str, price: float) -> int:
        async with self._get_db() as db:
            cursor = await db.execute(
                """INSERT INTO services (venue_id, name, description, price)
                   VALUES (?, ?, ?, ?)""",
                (venue_id, name, description, price)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_venue_services(self, venue_id: int) -> List[Service]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM services WHERE venue_id = ?", (venue_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [Service(**dict(row)) for row in rows]

    async def get_service(self, service_id: int) -> Optional[Service]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM services WHERE service_id = ?", (service_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Service(**dict(row))
                return None

    async def update_service(self, service_id: int, **kwargs):
        async with self._get_db() as db:
            set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            values = list(kwargs.values()) + [service_id]
            await db.execute(
                f"UPDATE services SET {set_clause} WHERE service_id = ?",
                values
            )
            await db.commit()

    async def delete_service(self, service_id: int):
        async with self._get_db() as db:
            await db.execute("DELETE FROM services WHERE service_id = ?", (service_id,))
            await db.commit()

    async def create_order(self, venue_id: int, table_number: int, 
                          user_id: int, service_id: int, song_name: str, status: str = "pending") -> int:
        async with self._get_db() as db:
            async with db.execute(
                """SELECT MAX(position) FROM orders 
                   WHERE venue_id = ? AND table_number = ? AND status IN ('pending', 'waiting')""",
                (venue_id, table_number)
            ) as cursor:
                row = await cursor.fetchone()
                position = (row[0] or 0) + 1

            cursor = await db.execute(
                """INSERT INTO orders (venue_id, table_number, user_id, service_id, 
                   song_name, position, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (venue_id, table_number, user_id, service_id, song_name, position, status)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_venue_orders(self, venue_id: int, status: str = "pending") -> List[Order]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM orders 
                   WHERE venue_id = ? AND status = ?
                   ORDER BY is_next DESC, marked_next_at ASC, position ASC""",
                (venue_id, status)
            ) as cursor:
                rows = await cursor.fetchall()
                orders = []
                for row in rows:
                    data = dict(row)
                    data.pop("artist_name", None)
                    data.pop("song_id", None)
                    orders.append(Order(**data))
                return orders

    async def get_table_orders(self, venue_id: int, table_number: int, 
                              status: str = "pending") -> List[Order]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM orders 
                   WHERE venue_id = ? AND table_number = ? AND status = ?
                   ORDER BY is_next DESC, marked_next_at ASC, position ASC""",
                (venue_id, table_number, status)
            ) as cursor:
                rows = await cursor.fetchall()
                orders = []
                for row in rows:
                    data = dict(row)
                    data.pop("artist_name", None)
                    data.pop("song_id", None)
                    orders.append(Order(**data))
                return orders

    async def update_order_status(self, order_id: int, status: str):
        async with self._get_db() as db:
            completed_at = datetime.now().isoformat() if status == "completed" else None
            started_at = datetime.now().isoformat() if status == "playing" else None
            cancelled_at = datetime.now().isoformat() if status in ("cancelled", "deleted") else None
            await db.execute(
                """UPDATE orders SET status = ?, completed_at = COALESCE(?, completed_at),
                   started_at = COALESCE(?, started_at),
                   cancelled_at = COALESCE(?, cancelled_at)
                   WHERE order_id = ?""",
                (status, completed_at, started_at, cancelled_at, order_id)
            )
            await db.commit()

    async def get_order_global_rank(self, venue_id: int, order_id: int) -> int:
        async with self._get_db() as db:
            async with db.execute(
                """SELECT order_id FROM orders
                   WHERE venue_id = ? AND status = 'pending'
                   ORDER BY is_next DESC, marked_next_at ASC, position ASC""",
                (venue_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                for rank, row in enumerate(rows, start=1):
                    if row[0] == order_id:
                        return rank
                return 0

    async def update_order_position(self, order_id: int, new_position: int):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE orders SET position = ? WHERE order_id = ?",
                (new_position, order_id)
            )
            await db.commit()

    async def toggle_order_next(self, order_id: int) -> bool:
        async with self._get_db() as db:
            async with db.execute(
                "SELECT is_next FROM orders WHERE order_id = ?",
                (order_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return False
                current = row[0] or 0

            if current:
                await db.execute(
                    "UPDATE orders SET is_next = 0, marked_next_at = NULL WHERE order_id = ?",
                    (order_id,)
                )
                await db.commit()
                return False
            else:
                await db.execute(
                    "UPDATE orders SET is_next = 1, marked_next_at = CURRENT_TIMESTAMP WHERE order_id = ?",
                    (order_id,)
                )
                await db.commit()
                return True

    async def update_order_song(self, order_id: int, song_name: str):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE orders SET song_name = ? WHERE order_id = ?",
                (song_name, order_id)
            )
            await db.commit()

    async def delete_order(self, order_id: int):
        await self.update_order_status(order_id, "deleted")

    async def add_vip_client(self, user_id: int, venue_id: int, 
                            cashback_percent: float = 0):
        async with self._get_db() as db:
            await db.execute(
                """INSERT INTO vip_clients (user_id, venue_id, cashback_percent)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, venue_id) DO UPDATE SET cashback_percent = excluded.cashback_percent""",
                (user_id, venue_id, cashback_percent)
            )
            await db.commit()

    async def get_vip_client(self, user_id: int, venue_id: int) -> Optional[VIPClient]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM vip_clients 
                   WHERE user_id = ? AND venue_id = ?""",
                (user_id, venue_id)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return VIPClient(**dict(row))
        return None

    async def update_vip_balance(self, user_id: int, venue_id: int, 
                                amount: float, add: bool = True):
        async with self._get_db() as db:
            if add:
                await db.execute(
                    """UPDATE vip_clients SET balance = balance + ? 
                       WHERE user_id = ? AND venue_id = ?""",
                    (amount, user_id, venue_id)
                )
            else:
                await db.execute(
                    """UPDATE vip_clients SET balance = balance - ? 
                       WHERE user_id = ? AND venue_id = ?""",
                    (amount, user_id, venue_id)
                )
            await db.commit()

    async def set_vip_balance(self, user_id: int, venue_id: int, balance: float):
        async with self._get_db() as db:
            await db.execute(
                """UPDATE vip_clients SET balance = ? 
                   WHERE user_id = ? AND venue_id = ?""",
                (balance, user_id, venue_id)
            )
            await db.commit()

    async def update_vip_cashback(self, user_id: int, venue_id: int, 
                                 cashback_percent: float):
        async with self._get_db() as db:
            await db.execute(
                """UPDATE vip_clients SET cashback_percent = ? 
                   WHERE user_id = ? AND venue_id = ?""",
                (cashback_percent, user_id, venue_id)
            )
            await db.commit()

    async def record_transaction(self, venue_id: int, user_id: int, amount: float,
                                  tx_type: str, description: str = "", order_id: int = None):
        async with self._get_db() as db:
            await db.execute(
                """INSERT INTO transactions (venue_id, user_id, order_id, amount, type, description)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (venue_id, user_id, order_id, amount, tx_type, description)
            )
            await db.commit()

    async def charge_vip_for_order(self, user_id: int, venue_id: int,
                                    amount: float, order_id: int, song_name: str = ""):
        await self.update_vip_balance(user_id, venue_id, amount, add=False)
        await self.record_transaction(
            venue_id, user_id, amount, 'order_payment',
            f'Оплата заказа #{order_id}: {song_name}', order_id
        )

    async def refund_vip_for_order(self, order_id: int):
        order = await self.get_order(order_id)
        if not order:
            return 0

        service = await self.get_service(order.service_id)
        if not service or service.is_free:
            return 0

        vip = await self.get_vip_client(order.user_id, order.venue_id)
        if not vip:
            return 0

        async with self._get_db() as db:
            async with db.execute(
                """SELECT COUNT(*) FROM transactions
                   WHERE order_id = ? AND type = 'order_refund'""",
                (order_id,)
            ) as cursor:
                already_refunded = (await cursor.fetchone())[0] > 0

        if already_refunded:
            return 0

        async with self._get_db() as db:
            async with db.execute(
                """SELECT amount FROM transactions
                   WHERE order_id = ? AND type = 'order_payment'""",
                (order_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return 0
                paid_amount = row[0]

        await self.update_vip_balance(order.user_id, order.venue_id, paid_amount, add=True)
        await self.record_transaction(
            order.venue_id, order.user_id, paid_amount, 'order_refund',
            f'Возврат за заказ #{order_id}: {order.song_name}', order_id
        )
        return paid_amount

    async def log_event(self, event_type: str, venue_id: int = None,
                        user_id: int = None, details: str = None):
        async with self._get_db() as db:
            await db.execute(
                """INSERT INTO event_log (venue_id, user_id, event_type, details)
                   VALUES (?, ?, ?, ?)""",
                (venue_id, user_id, event_type, details)
            )
            await db.commit()

    async def update_daily_stats(self, venue_id: int, date: str = None):
        if not date:
            date = get_stats_date()

        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row

            async with db.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                          SUM(CASE WHEN status IN ('cancelled', 'deleted') THEN 1 ELSE 0 END) as cancelled
                   FROM orders WHERE venue_id = ? AND DATE(created_at) = ?""",
                (venue_id, date)
            ) as cursor:
                row = await cursor.fetchone()
                total_orders = row['total'] or 0
                completed_orders = row['completed'] or 0
                cancelled_orders = row['cancelled'] or 0

            async with db.execute(
                """SELECT COALESCE(SUM(s.price), 0) as revenue
                   FROM orders o JOIN services s ON o.service_id = s.service_id
                   WHERE o.venue_id = ? AND o.status = 'completed' AND DATE(o.completed_at) = ?""",
                (venue_id, date)
            ) as cursor:
                total_revenue = (await cursor.fetchone())['revenue'] or 0

            async with db.execute(
                """SELECT COALESCE(SUM(t.amount), 0) as vip_rev
                   FROM transactions t
                   WHERE t.venue_id = ? AND t.type = 'order_payment' AND DATE(t.created_at) = ?""",
                (venue_id, date)
            ) as cursor:
                vip_revenue = (await cursor.fetchone())['vip_rev'] or 0

            regular_revenue = total_revenue - vip_revenue
            if regular_revenue < 0:
                regular_revenue = 0

            async with db.execute(
                """SELECT COUNT(DISTINCT user_id) as cnt FROM orders
                   WHERE venue_id = ? AND DATE(created_at) = ?""",
                (venue_id, date)
            ) as cursor:
                unique_users = (await cursor.fetchone())['cnt'] or 0

            async with db.execute(
                """SELECT COUNT(*) as cnt FROM users
                   WHERE venue_id = ? AND DATE(created_at) = ?""",
                (venue_id, date)
            ) as cursor:
                new_users = (await cursor.fetchone())['cnt'] or 0

            async with db.execute(
                """SELECT COALESCE(SUM(amount), 0) as total_topups FROM transactions
                   WHERE venue_id = ? AND type = 'topup' AND DATE(created_at) = ?""",
                (venue_id, date)
            ) as cursor:
                total_topups = (await cursor.fetchone())['total_topups'] or 0

            async with db.execute(
                """SELECT COALESCE(SUM(amount), 0) as total_cb FROM transactions
                   WHERE venue_id = ? AND type = 'cashback' AND DATE(created_at) = ?""",
                (venue_id, date)
            ) as cursor:
                total_cashback = (await cursor.fetchone())['total_cb'] or 0

            async with db.execute(
                """SELECT AVG(
                       (JULIANDAY(started_at) - JULIANDAY(created_at)) * 24 * 60
                   ) as avg_wait
                   FROM orders
                   WHERE venue_id = ? AND started_at IS NOT NULL AND DATE(created_at) = ?""",
                (venue_id, date)
            ) as cursor:
                avg_wait_time = (await cursor.fetchone())['avg_wait'] or 0

            await db.execute(
                """INSERT INTO daily_stats
                   (venue_id, date, total_orders, completed_orders, cancelled_orders,
                    total_revenue, vip_revenue, regular_revenue, unique_users, new_users,
                    total_topups, total_cashback, total_songs_played, avg_wait_time, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(venue_id, date) DO UPDATE SET
                    total_orders=excluded.total_orders,
                    completed_orders=excluded.completed_orders,
                    cancelled_orders=excluded.cancelled_orders,
                    total_revenue=excluded.total_revenue,
                    vip_revenue=excluded.vip_revenue,
                    regular_revenue=excluded.regular_revenue,
                    unique_users=excluded.unique_users,
                    new_users=excluded.new_users,
                    total_topups=excluded.total_topups,
                    total_cashback=excluded.total_cashback,
                    total_songs_played=excluded.completed_orders,
                    avg_wait_time=excluded.avg_wait_time,
                    updated_at=CURRENT_TIMESTAMP""",
                (venue_id, date, total_orders, completed_orders, cancelled_orders,
                 total_revenue, vip_revenue, regular_revenue, unique_users, new_users,
                 total_topups, total_cashback, completed_orders, round(avg_wait_time, 1))
            )
            await db.commit()

    async def get_daily_stats(self, venue_id: int, date: str = None):
        if not date:
            date = get_stats_date()

        await self.update_daily_stats(venue_id, date)

        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM daily_stats WHERE venue_id = ? AND date = ?",
                (venue_id, date)
            ) as cursor:
                return await cursor.fetchone()

    async def get_period_stats(self, venue_id: int, days: int = 7):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT
                    SUM(total_orders) as total_orders,
                    SUM(completed_orders) as completed_orders,
                    SUM(cancelled_orders) as cancelled_orders,
                    SUM(total_revenue) as total_revenue,
                    SUM(vip_revenue) as vip_revenue,
                    SUM(regular_revenue) as regular_revenue,
                    SUM(unique_users) as unique_users,
                    SUM(new_users) as new_users,
                    SUM(total_topups) as total_topups,
                    SUM(total_cashback) as total_cashback,
                    SUM(total_songs_played) as total_songs_played,
                    AVG(avg_wait_time) as avg_wait_time
                   FROM daily_stats
                   WHERE venue_id = ? AND date >= DATE('now', ?)""",
                (venue_id, f'-{days} days')
            ) as cursor:
                return await cursor.fetchone()

    async def get_top_songs(self, venue_id: int, days: int = 30, limit: int = 10):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT song_name, COUNT(*) as order_count
                   FROM orders
                   WHERE venue_id = ? AND DATE(created_at) >= DATE('now', ?)
                   GROUP BY song_name
                   ORDER BY order_count DESC
                   LIMIT ?""",
                (venue_id, f'-{days} days', limit)
            ) as cursor:
                return await cursor.fetchall()

    async def get_top_users(self, venue_id: int, days: int = 30, limit: int = 10):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT u.user_id, u.first_name, u.username, COUNT(o.order_id) as order_count,
                          COALESCE(SUM(s.price), 0) as total_spent
                   FROM orders o
                   JOIN users u ON o.user_id = u.user_id
                   JOIN services s ON o.service_id = s.service_id
                   WHERE o.venue_id = ? AND DATE(o.created_at) >= DATE('now', ?)
                   AND o.status = 'completed'
                   GROUP BY u.user_id
                   ORDER BY order_count DESC
                   LIMIT ?""",
                (venue_id, f'-{days} days', limit)
            ) as cursor:
                return await cursor.fetchall()

    async def get_service_stats(self, venue_id: int, days: int = 30):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT s.name, s.price, COUNT(o.order_id) as count,
                          COALESCE(SUM(s.price), 0) as total
                   FROM orders o
                   JOIN services s ON o.service_id = s.service_id
                   WHERE o.venue_id = ? AND o.status = 'completed'
                   AND DATE(o.completed_at) >= DATE('now', ?)
                   GROUP BY s.service_id
                   ORDER BY count DESC""",
                (venue_id, f'-{days} days')
            ) as cursor:
                return await cursor.fetchall()

    async def get_hourly_distribution(self, venue_id: int, days: int = 30):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT CAST(strftime('%H', created_at) AS INTEGER) as hour,
                          COUNT(*) as count
                   FROM orders
                   WHERE venue_id = ? AND DATE(created_at) >= DATE('now', ?)
                   GROUP BY hour
                   ORDER BY hour""",
                (venue_id, f'-{days} days')
            ) as cursor:
                return await cursor.fetchall()

    async def get_vip_stats(self, venue_id: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT COUNT(*) as total_vips,
                          COALESCE(SUM(balance), 0) as total_balance,
                          COALESCE(AVG(balance), 0) as avg_balance
                   FROM vip_clients WHERE venue_id = ?""",
                (venue_id,)
            ) as cursor:
                return await cursor.fetchone()

    async def get_event_log(self, venue_id: int = None, event_type: str = None,
                            days: int = 7, limit: int = 50):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            conditions = []
            params = []

            if venue_id:
                conditions.append("venue_id = ?")
                params.append(venue_id)
            if event_type:
                conditions.append("event_type = ?")
                params.append(event_type)
            if days:
                conditions.append("DATE(created_at) >= DATE('now', ?)")
                params.append(f'-{days} days')

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            async with db.execute(
                f"""SELECT * FROM event_log {where}
                    ORDER BY created_at DESC LIMIT ?""",
                tuple(params) + (limit,)
            ) as cursor:
                return await cursor.fetchall()

    async def add_song(self, venue_id: int, artist: str, title: str, 
                      code: Optional[str] = None):
        async with self._get_db() as db:
            await db.execute(
                """INSERT INTO songs (venue_id, artist, title, code)
                   VALUES (?, ?, ?, ?)""",
                (venue_id, artist, title, code)
            )
            await db.commit()

    async def search_songs(self, venue_id: int, query: str) -> List[Song]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM songs 
                   WHERE venue_id = ? AND (
                       artist LIKE ? OR title LIKE ? OR code LIKE ?
                   )
                   LIMIT 20""",
                (venue_id, f"%{query}%", f"%{query}%", f"%{query}%")
            ) as cursor:
                rows = await cursor.fetchall()
                return [Song(**dict(row)) for row in rows]

    async def bulk_add_songs(self, venue_id: int, songs: list) -> int:
        async with self._get_db() as db:
            async with db.execute(
                "SELECT title FROM songs WHERE venue_id = ?",
                (venue_id,)
            ) as cursor:
                rows = await cursor.fetchall()
            existing_titles = {row[0].lower() for row in rows}

            new_songs = [
                s for s in songs
                if s['title'].lower() not in existing_titles
            ]

            if new_songs:
                await db.executemany(
                    "INSERT INTO songs (venue_id, artist, title, code) VALUES (?, ?, ?, ?)",
                    [(venue_id, s['artist'], s['title'], s.get('code')) for s in new_songs]
                )
                await db.commit()

            return len(new_songs)

    async def clear_venue_songs(self, venue_id: int):
        async with self._get_db() as db:
            await db.execute("DELETE FROM songs WHERE venue_id = ?", (venue_id,))
            await db.commit()

    async def get_daily_revenue(self, venue_id: int, date: str = None) -> float:
        if not date:
            date = get_stats_date()
        
        async with self._get_db() as db:
            async with db.execute(
                """SELECT SUM(s.price) FROM orders o
                   JOIN services s ON o.service_id = s.service_id
                   WHERE o.venue_id = ? AND o.status = 'completed'
                   AND DATE(o.completed_at) = ?""",
                (venue_id, date)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] or 0

    async def get_period_revenue(self, venue_id: int, start_date: str, end_date: str) -> float:
        async with self._get_db() as db:
            async with db.execute(
                """SELECT SUM(s.price) FROM orders o
                   JOIN services s ON o.service_id = s.service_id
                   WHERE o.venue_id = ? AND o.status = 'completed'
                   AND DATE(o.completed_at) BETWEEN ? AND ?""",
                (venue_id, start_date, end_date)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] or 0

    async def get_venue_stats(self, venue_id: int, date: str = None):
        if not date:
            date = get_stats_date()
        
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT s.name, s.price, COUNT(*) as count, 
                   SUM(s.price) as total
                   FROM orders o
                   JOIN services s ON o.service_id = s.service_id
                   WHERE o.venue_id = ? AND o.status = 'completed'
                   AND DATE(o.completed_at) = ?
                   GROUP BY s.service_id""",
                (venue_id, date)
            ) as cursor:
                return await cursor.fetchall()

    async def get_user_by_venue(self, venue_id: int) -> Optional[User]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM users 
                   WHERE venue_id = ? AND role = ?""",
                (venue_id, config.ROLE_KJ)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return User(**dict(row))
        return None

    async def get_song_count(self, venue_id: int) -> int:
        async with self._get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM songs WHERE venue_id = ?",
                (venue_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_all_kj(self) -> List[User]:
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE role = ?",
                (config.ROLE_KJ,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [User(**dict(row)) for row in rows]

    async def get_venue_orders_count(self, venue_id: int, status: str = "completed", date: str = None) -> int:
        if not date:
            date = get_stats_date()
        
        async with self._get_db() as db:
            async with db.execute(
                """SELECT COUNT(*) FROM orders 
                   WHERE venue_id = ? AND status = ? AND DATE(completed_at) = ?""",
                (venue_id, status, date)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_weekly_revenue(self, venue_id: int = None) -> float:
        async with self._get_db() as db:
            if venue_id:
                query = """SELECT SUM(s.price) FROM orders o
                          JOIN services s ON o.service_id = s.service_id
                          WHERE o.venue_id = ? AND o.status = 'completed'
                          AND DATE(o.completed_at) >= DATE('now', '-7 days')"""
                params = (venue_id,)
            else:
                query = """SELECT SUM(s.price) FROM orders o
                          JOIN services s ON o.service_id = s.service_id
                          WHERE o.status = 'completed'
                          AND DATE(o.completed_at) >= DATE('now', '-7 days')"""
                params = ()
            
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return row[0] or 0

    async def get_monthly_revenue(self, venue_id: int = None) -> float:
        async with self._get_db() as db:
            if venue_id:
                query = """SELECT SUM(s.price) FROM orders o
                          JOIN services s ON o.service_id = s.service_id
                          WHERE o.venue_id = ? AND o.status = 'completed'
                          AND DATE(o.completed_at) >= DATE('now', '-30 days')"""
                params = (venue_id,)
            else:
                query = """SELECT SUM(s.price) FROM orders o
                          JOIN services s ON o.service_id = s.service_id
                          WHERE o.status = 'completed'
                          AND DATE(o.completed_at) >= DATE('now', '-30 days')"""
                params = ()
            
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return row[0] or 0

    async def apply_cashback(self, user_id: int, venue_id: int, order_amount: float, order_id: int = None) -> float:
        vip = await self.get_vip_client(user_id, venue_id)
        if not vip or vip.cashback_percent == 0:
            return 0
        
        cashback_amount = round(order_amount * (vip.cashback_percent / 100), 2)
        await self.update_vip_balance(user_id, venue_id, cashback_amount, add=True)
        
        await self.record_transaction(
            venue_id, user_id, cashback_amount, 'cashback',
            f'Кешбек от заказа #{order_id}' if order_id else 'Кешбек от заказа',
            order_id
        )
        
        return cashback_amount

    async def reorder_queue(self, venue_id: int, table_number: int):
        async with self._get_db() as db:
            async with db.execute(
                """SELECT order_id FROM orders 
                   WHERE venue_id = ? AND table_number = ? AND status = 'pending'
                   ORDER BY is_next DESC, marked_next_at ASC, position ASC""",
                (venue_id, table_number)
            ) as cursor:
                rows = await cursor.fetchall()
            
            for idx, row in enumerate(rows, 1):
                await db.execute(
                    "UPDATE orders SET position = ? WHERE order_id = ?",
                    (idx, row[0])
                )
            await db.commit()

    async def add_to_favorites(self, user_id: int, venue_id: int, song_id: int, service_id: int):
        async with self._get_db() as db:
            await db.execute(
                """INSERT INTO favorites (user_id, venue_id, song_id, service_id)
                   VALUES (?, ?, ?, ?)""",
                (user_id, venue_id, song_id, service_id)
            )
            await db.commit()

    async def remove_from_favorites(self, favorite_id: int):
        async with self._get_db() as db:
            await db.execute("DELETE FROM favorites WHERE favorite_id = ?", (favorite_id,))
            await db.commit()

    async def get_user_favorites(self, user_id: int, venue_id: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT f.favorite_id, s.song_id, s.artist, s.title, srv.name as service_name
                   FROM favorites f
                   JOIN songs s ON f.song_id = s.song_id
                   JOIN services srv ON f.service_id = srv.service_id
                   WHERE f.user_id = ? AND f.venue_id = ?
                   ORDER BY f.added_at DESC""",
                (user_id, venue_id)
            ) as cursor:
                return await cursor.fetchall()

    async def search_songs(self, venue_id: int, query: str, limit: int = 10):
        if not query:
            return []

        query_norm = " ".join(query.split()).casefold()
        if not query_norm:
            return []

        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT song_id, artist, title, code FROM songs
                   WHERE venue_id = ?""",
                (venue_id,)
            ) as cursor:
                rows = await cursor.fetchall()

        matches = []
        for row in rows:
            artist = (row["artist"] or "").strip()
            title = (row["title"] or "").strip()
            code = (row["code"] or "").strip()
            combined = f"{artist} - {title}".strip(" -")

            haystack = " ".join(filter(None, [artist, title, code, combined])).casefold()
            if query_norm in haystack:
                matches.append(row)
                if len(matches) >= limit:
                    break

        return matches

    async def create_request(self, venue_id: int, user_id: int, table_number: int, request_type: str, amount: float = 0):
        async with self._get_db() as db:
            cursor = await db.execute(
                """INSERT INTO requests (venue_id, user_id, table_number, request_type, amount)
                   VALUES (?, ?, ?, ?, ?)""",
                (venue_id, user_id, table_number, request_type, amount)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_pending_requests(self, venue_id: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT r.*, u.username, u.first_name
                   FROM requests r
                   JOIN users u ON r.user_id = u.user_id
                   WHERE r.venue_id = ? AND r.status = 'pending'
                   ORDER BY r.created_at ASC""",
                (venue_id,)
            ) as cursor:
                return await cursor.fetchall()

    async def update_request_status(self, request_id: int, status: str):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE requests SET status = ? WHERE request_id = ?",
                (status, request_id)
            )
            await db.commit()

    async def send_message(self, venue_id: int, from_user_id: int, to_user_id: int, 
                          message_text: str, table_number: int = None):
        async with self._get_db() as db:
            await db.execute(
                """INSERT INTO chat_messages (venue_id, from_user_id, to_user_id, message_text, table_number)
                   VALUES (?, ?, ?, ?, ?)""",
                (venue_id, from_user_id, to_user_id, message_text, table_number)
            )
            await db.commit()
    
    async def save_chat_message(self, venue_id: int, from_user_id: int, to_user_id: int, 
                          message_text: str, table_number: int = None):
        await self.send_message(venue_id, from_user_id, to_user_id, message_text, table_number)

    async def get_unread_messages(self, user_id: int, venue_id: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT m.*, u.username, u.first_name
                   FROM chat_messages m
                   JOIN users u ON m.from_user_id = u.user_id
                   WHERE m.to_user_id = ? AND m.venue_id = ? AND m.is_read = 0
                   ORDER BY m.created_at ASC""",
                (user_id, venue_id)
            ) as cursor:
                return await cursor.fetchall()

    async def mark_messages_read(self, user_id: int, venue_id: int):
        async with self._get_db() as db:
            await db.execute(
                """UPDATE chat_messages SET is_read = 1
                   WHERE to_user_id = ? AND venue_id = ? AND is_read = 0""",
                (user_id, venue_id)
            )
            await db.commit()

    async def get_user_orders_history(self, user_id: int, venue_id: int, days: int = None):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            if days:
                query = """SELECT o.*, s.artist, s.title, srv.name as service_name, srv.price
                           FROM orders o
                           JOIN songs s ON o.song_name = s.title
                           JOIN services srv ON o.service_id = srv.service_id
                           WHERE o.user_id = ? AND o.venue_id = ? 
                           AND DATE(o.created_at) >= DATE('now', ?)
                           ORDER BY o.created_at DESC"""
                params = (user_id, venue_id, f'-{days} days')
            else:
                query = """SELECT o.*, s.artist, s.title, srv.name as service_name, srv.price
                           FROM orders o
                           JOIN songs s ON o.song_name = s.title
                           JOIN services srv ON o.service_id = srv.service_id
                           WHERE o.user_id = ? AND o.venue_id = ?
                           ORDER BY o.created_at DESC"""
                params = (user_id, venue_id)
            
            async with db.execute(query, params) as cursor:
                return await cursor.fetchall()

    async def get_user_transactions(self, user_id: int, venue_id: int, transaction_type: str = None, days: int = None):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            conditions = ["user_id = ?", "venue_id = ?"]
            params = [user_id, venue_id]
            
            if transaction_type:
                conditions.append("type = ?")
                params.append(transaction_type)
            
            if days:
                conditions.append("DATE(created_at) >= DATE('now', ?)")
                params.append(f'-{days} days')
            
            query = f"""SELECT * FROM transactions
                       WHERE {' AND '.join(conditions)}
                       ORDER BY created_at DESC"""
            
            async with db.execute(query, tuple(params)) as cursor:
                return await cursor.fetchall()

    async def update_user_table(self, user_id: int, table_number: int):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE users SET table_number = ? WHERE user_id = ?",
                (table_number, user_id)
            )
            await db.commit()

    async def update_table_number(self, user_id: int, table_number: int):
        await self.update_user_table(user_id, table_number)

    async def get_song(self, song_id: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM songs WHERE song_id = ?", (song_id,)
            ) as cursor:
                return await cursor.fetchone()

    async def get_order(self, order_id: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM orders WHERE order_id = ?", (order_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    data = dict(row)
                    data.pop("artist_name", None)
                    data.pop("song_id", None)
                    return Order(**data)
        return None

    async def get_orders_by_table(self, venue_id: int, table_number: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM orders 
                   WHERE venue_id = ? AND table_number = ? AND status = 'pending'
                   ORDER BY is_next DESC, marked_next_at ASC, position ASC""",
                (venue_id, table_number)
            ) as cursor:
                rows = await cursor.fetchall()
                orders = []
                for row in rows:
                    data = dict(row)
                    data.pop("artist_name", None)
                    data.pop("song_id", None)
                    orders.append(Order(**data))
                return orders

    async def import_songs_from_csv(self, csv_path: str):
        async with self._get_db() as db:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                for row in reader:
                    try:
                        await db.execute(
                            """INSERT INTO songs (venue_id, artist, title, code) 
                               VALUES (?, ?, ?, ?)""",
                            (
                                int(row['Venue_id']),
                                row['artis'].strip(),
                                row['title'].strip(),
                                row['id']
                            )
                        )
                    except Exception:
                        continue
            await db.commit()

    async def search_songs(self, venue_id: int, query: str, limit: int = 50):
        if not query:
            return []

        query_norm = " ".join(query.split()).casefold()
        if not query_norm:
            return []

        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM songs WHERE venue_id = ? ORDER BY artist, title""",
                (venue_id,)
            ) as cursor:
                rows = await cursor.fetchall()

        matches = []
        for row in rows:
            artist = (row["artist"] or "").strip()
            title = (row["title"] or "").strip()
            code = (row["code"] or "").strip()
            combined = f"{artist} - {title}".strip(" -")

            haystack = " ".join(filter(None, [artist, title, code, combined])).casefold()
            if query_norm in haystack:
                matches.append(Song(**dict(row)))
                if len(matches) >= limit:
                    break

        return matches

    async def get_songs(self, venue_id: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM songs WHERE venue_id = ?",
                (venue_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [Song(**dict(row)) for row in rows]

    async def get_table_orders_count(self, venue_id: int, table_number: int = None):
        async with self._get_db() as db:
            if table_number:
                async with db.execute(
                    "SELECT COUNT(*) FROM orders WHERE venue_id = ? AND table_number = ? AND status IN ('pending', 'waiting')",
                    (venue_id, table_number)
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else 0
            else:
                async with db.execute(
                    "SELECT COUNT(*) FROM orders WHERE venue_id = ? AND status IN ('pending', 'waiting')",
                    (venue_id,)
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else 0

    async def get_kj_by_venue(self, venue_id: int):
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE venue_id = ? AND role = ?",
                (venue_id, config.ROLE_KJ)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return User(**dict(row))
        return None

    async def update_venue_name(self, venue_id: int, name: str):
        async with self._get_db() as db:
            await db.execute(
                "UPDATE venues SET name = ? WHERE venue_id = ?",
                (name, venue_id)
            )
            await db.commit()
