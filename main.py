import os
import sqlite3
import hmac
import hashlib
import json
from urllib.parse import parse_qsl
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

DB_NAME = "blackout.db"

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

def verify_telegram_data(init_data):
    if not BOT_TOKEN or not init_data:
        return None

    data = dict(parse_qsl(init_data))
    received_hash = data.pop("hash", None)

    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items())
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

@app.route("/")
def home():
    return send_from_directory("frontend", "index.html")

@app.route("/health")
def health():
    return jsonify({"status": "ONLINE", "project": "BLACKOUT"})

@app.route("/api/auth", methods=["POST"])
def auth():
    data = request.get_json(silent=True) or {}
    verified = verify_telegram_data(data.get("initData"))

    if not verified:
        return jsonify({"error": "Unauthorized"}), 401

    user = json.loads(verified["user"])
    telegram_id = str(user["id"])
    username = user.get("username", "Player")

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

@app.route("/api/tap", methods=["POST"])
def tap():
    data = request.get_json(silent=True) or {}
    verified = verify_telegram_data(data.get("initData"))

    if not verified:
        return jsonify({"error": "Unauthorized"}), 401

    user = json.loads(verified["user"])
    telegram_id = str(user["id"])

    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            INSERT INTO users (telegram_id, username)
            VALUES (?, ?)
            ON CONFLICT(telegram_id) DO NOTHING
        """, (telegram_id, user.get("username", "Player")))

        db.execute(
            "UPDATE users SET balance=balance+1 WHERE telegram_id=?",
            (telegram_id,)
        )

        balance = db.execute(
            "SELECT balance FROM users WHERE telegram_id=?",
            (telegram_id,)
        ).fetchone()[0]

    return jsonify({"balance": balance})

init_db()
