import os
import sqlite3
import hmac
import hashlib
import json
import random

from datetime import datetime, timezone
from urllib.parse import parse_qsl
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DB_NAME = "blackout.db"


# НАГРАДЫ КЕЙСА
CASE_ITEMS = [
    {"name": "+888 0000 888", "rarity": "COMMON", "weight": 350},
    {"name": "+888 0111 111", "rarity": "COMMON", "weight": 350},
    {"name": "+888 0777 777", "rarity": "RARE", "weight": 115},
    {"name": "+888 0888 888", "rarity": "RARE", "weight": 115},
    {"name": "+888 0999 999", "rarity": "EPIC", "weight": 30},
    {"name": "+888 0666 666", "rarity": "EPIC", "weight": 30},
    {"name": "+888 0000 001", "rarity": "LEGENDARY", "weight": 10}
]


CASES = {
    "starter": {
        "name": "STARTER CASE",
        "price": 100
    }
}


# БАЗА ДАННЫХ
def init_db():
    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT UNIQUE,
                username TEXT,
                balance INTEGER DEFAULT 0,
                role TEXT DEFAULT 'USER'
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT,
                item_name TEXT,
                rarity TEXT,
                created_at TEXT
            )
        """)


# ПРОВЕРКА TELEGRAM
def verify_telegram_data(init_data):
    if not BOT_TOKEN or not init_data:
        return None

    data = dict(parse_qsl(init_data))
    received_hash = data.pop("hash", None)

    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(data.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    return data


def get_verified_user():
    data = request.get_json(silent=True) or {}
    verified = verify_telegram_data(data.get("initData"))

    if not verified or "user" not in verified:
        return None

    try:
        return json.loads(verified["user"])
    except (ValueError, TypeError):
        return None


# ГЛАВНАЯ
@app.route("/")
def home():
    return send_from_directory("frontend", "index.html")


@app.route("/health")
def health():
    return jsonify({
        "status": "ONLINE",
        "project": "BLACKOUT"
    })


# АВТОРИЗАЦИЯ
@app.route("/api/auth", methods=["POST"])
def auth():
    user = get_verified_user()

    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    telegram_id = str(user["id"])
    username = user.get("username") or "Player"

    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            INSERT INTO users (telegram_id, username)
            VALUES (?, ?)
            ON CONFLICT(telegram_id)
            DO UPDATE SET username=excluded.username
        """, (telegram_id, username))

        row = db.execute(
            "SELECT balance, role FROM users WHERE telegram_id=?",
            (telegram_id,)
        ).fetchone()

    return jsonify({
        "username": username,
        "balance": row[0],
        "role": row[1]
    })


# НАЖАТИЯ
@app.route("/api/tap", methods=["POST"])
def tap():
    user = get_verified_user()

    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    telegram_id = str(user["id"])

    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            INSERT INTO users (telegram_id, username)
            VALUES (?, ?)
            ON CONFLICT(telegram_id) DO NOTHING
        """, (telegram_id, user.get("username") or "Player"))

        db.execute(
            "UPDATE users SET balance=balance+1 WHERE telegram_id=?",
            (telegram_id,)
        )

        balance = db.execute(
            "SELECT balance FROM users WHERE telegram_id=?",
            (telegram_id,)
        ).fetchone()[0]

    return jsonify({"balance": balance})


# СПИСОК КЕЙСОВ
@app.route("/api/cases", methods=["GET"])
def get_cases():
    result = []

    for case_id, case in CASES.items():
        result.append({
            "id": case_id,
            "name": case["name"],
            "price": case["price"]
        })

    return jsonify({"cases": result})


# ОТКРЫТИЕ КЕЙСА
@app.route("/api/open-case", methods=["POST"])
def open_case():
    user = get_verified_user()

    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    case_id = data.get("case_id")

    if case_id not in CASES:
        return jsonify({"error": "Кейс не найден"}), 404

    telegram_id = str(user["id"])
    case = CASES[case_id]
    price = case["price"]

    # Выбираем награду на сервере
    item = random.choices(
        CASE_ITEMS,
        weights=[x["weight"] for x in CASE_ITEMS],
        k=1
    )[0]

    try:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("BEGIN IMMEDIATE")

            row = db.execute(
                "SELECT balance FROM users WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()

            if not row:
                db.rollback()
                return jsonify({"error": "Пользователь не найден"}), 404

            balance = row[0]

            if balance < price:
                db.rollback()
                return jsonify({
                    "error": "Недостаточно NK",
                    "balance": balance,
                    "price": price
                }), 400

            new_balance = balance - price

            db.execute(
                "UPDATE users SET balance=? WHERE telegram_id=?",
                (new_balance, telegram_id)
            )

            db.execute("""
                INSERT INTO inventory
                (telegram_id, item_name, rarity, created_at)
                VALUES (?, ?, ?, ?)
            """, (
                telegram_id,
                item["name"],
                item["rarity"],
                datetime.now(timezone.utc).isoformat()
            ))

            db.commit()

    except sqlite3.Error:
        return jsonify({"error": "Ошибка базы данных"}), 500

    return jsonify({
        "success": True,
        "balance": new_balance,
        "item": {
            "name": item["name"],
            "rarity": item["rarity"]
        }
    })


# ИНВЕНТАРЬ
@app.route("/api/inventory", methods=["POST"])
def get_inventory():
    user = get_verified_user()

    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    telegram_id = str(user["id"])

    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute("""
            SELECT id, item_name, rarity, created_at
            FROM inventory
            WHERE telegram_id=?
            ORDER BY id DESC
        """, (telegram_id,)).fetchall()

    items = []

    for row in rows:
        items.append({
            "id": row[0],
            "name": row[1],
            "rarity": row[2],
            "created_at": row[3]
        })

    return jsonify({"items": items})


init_db()
