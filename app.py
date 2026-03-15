import secrets
from datetime import datetime, timedelta
import requests
import re
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask import Flask, request, jsonify
import pickle
import numpy as np
import pandas
import os

path = '.'  # for local host

pt = pickle.load(open(path + '/res/pt.pkl', 'rb'))
books = pickle.load(open(path + '/res/comp_books.pkl', 'rb'))
scores = pickle.load(open(path + '/res/scores.pkl', 'rb'))

app = Flask(__name__)
bcrypt = Bcrypt(app)
CORS(app)

# Brevo API Key (HTTP API - works on Render free tier)
BREVO_API_KEY = os.environ.get("BREVO_API_KEY")  # <-- paste your key here

# MongoDB Connection
client = MongoClient("mongodb+srv://Admin:reads123@smartreadsml.nykdwew.mongodb.net/smartreads?appName=SmartReadsML")
db = client["smartreads"]
users_collection = db["users"]


def send_reset_email(to_email, reset_link):
    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key": BREVO_API_KEY,
            "Content-Type": "application/json"
        },
        json={
            "sender": {"name": "SmartReadsML", "email": "mohitog07@gmail.com"},
            "to": [{"email": to_email}],
            "subject": "SmartReadsML - Password Reset",
            "textContent": f"Click to reset your password (valid 1 hour):\n{reset_link}"
        }
    )
    print("Brevo API response:", response.status_code, response.text)
    return response.status_code == 201


@app.route('/')
def index_ui():
    return jsonify('welcome'), 200


@app.route('/top50_api')
def top50_api():
    x = books.sort_values(by='avg_rating', ascending=False)
    data = [
        list(x['Book-Title'].values),
        list(x['Book-Author'].values),
        list(x['Image-URL-L'].values),
        list(x['num_ratings'].values),
        list(format(i, ".2f") for i in x['avg_rating'].values)
    ]

    res = []
    for i in range(50):
        res.append({
            'Book-title': str(data[0][i]),
            'Book-author': str(data[1][i]),
            'Image-URL-M': str(data[2][i]),
            'num_ratings': str(data[3][i]),
            'avg_ratings': str(data[4][i]),
        })
    return jsonify(res), 200


@app.route('/reccomendations_api', methods=['POST'])
def reccomendations_api():
    book_name = request.json['name']
    if len(np.where(pt.index == book_name)[0]) == 0:
        return jsonify({'status': 0, 'books': []}), 200

    idx = np.where(pt.index == book_name)[0][0]
    items = sorted(list(enumerate(scores[idx])),
                   key=lambda x: x[1], reverse=True)[1:20]

    data = []
    for i in items:
        item = []
        temp = books[books['Book-Title'] == pt.index[i[0]]]
        item.extend(list(temp.drop_duplicates('Book-Title')['Book-Title'].values))
        item.extend(list(temp.drop_duplicates('Book-Title')['Book-Author'].values))
        item.extend(list(temp.drop_duplicates('Book-Title')['Image-URL-L'].values))
        item.extend(list(temp.drop_duplicates('Book-Title')['num_ratings'].values.astype('str')))
        item.extend(list(temp.drop_duplicates('Book-Title')['avg_rating'].values.astype('str')))
        data.append(item)

    res = []
    for i in data:
        if len(i) == 0:
            continue
        res.append({
            'Book-title': i[0],
            'Book-author': i[1],
            'Image-URL-M': i[2],
            'num_ratings': i[3],
            'avg_rating': i[4]
        })

    return jsonify({'status': 1, 'books': res[:10]}), 200


@app.route('/book_names')
def book_names_api():
    return jsonify({'BookNames': list(books['Book-Title'])}), 200


# ---------------- AUTH SECTION ---------------- #

@app.route('/signup', methods=['POST'])
def signup():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    if not re.match(email_pattern, email):
        return jsonify({"message": "Invalid email format"}), 400

    blocked_domains = ["tempmail.com", "10minutemail.com", "mailinator.com"]
    domain = email.split("@")[1]
    if domain in blocked_domains:
        return jsonify({"message": "Disposable emails are not allowed"}), 400

    if users_collection.find_one({"email": email}):
        return jsonify({"message": "User already exists"}), 400

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    users_collection.insert_one({
        "email": email,
        "password": hashed_password
    })

    return jsonify({"message": "User created successfully"}), 201


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    user = users_collection.find_one({"email": email})

    if user and bcrypt.check_password_hash(user["password"], password):
        return jsonify({"message": "Login successful"}), 200

    return jsonify({"message": "Invalid credentials"}), 401


@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.json
    email = data.get("email")

    if not email:
        return jsonify({"message": "Email is required"}), 400

    user = users_collection.find_one({"email": email})
    if not user:
        return jsonify({"message": "Email not found"}), 404

    token = secrets.token_urlsafe(32)
    expiry = datetime.utcnow() + timedelta(hours=1)

    users_collection.update_one(
        {"email": email},
        {"$set": {"reset_token": token, "reset_expiry": expiry}}
    )

    reset_link = f"https://https://smartreads-app.vercel.app//reset-password/{token}"

    if send_reset_email(email, reset_link):
        return jsonify({"message": "Reset email sent!"}), 200
    else:
        return jsonify({"message": "Failed to send email"}), 500


@app.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.json
    token = data.get("token")
    new_password = data.get("password")

    user = users_collection.find_one({"reset_token": token})
    if not user:
        return jsonify({"message": "Invalid or expired token"}), 400

    if datetime.utcnow() > user["reset_expiry"]:
        return jsonify({"message": "Token has expired"}), 400

    hashed = bcrypt.generate_password_hash(new_password).decode('utf-8')
    users_collection.update_one(
        {"reset_token": token},
        {"$set": {"password": hashed}, "$unset": {"reset_token": "", "reset_expiry": ""}}
    )
    return jsonify({"message": "Password reset successful"}), 200


# ---------------- RATINGS SECTION ---------------- #

@app.route('/rate_book', methods=['POST'])
def rate_book():
    data = request.json
    email      = data.get('email')
    book_title = data.get('book_title')
    rating     = data.get('rating')

    if not email or not book_title or rating is None:
        return jsonify({'message': 'Missing fields'}), 400

    if not (1 <= int(rating) <= 5):
        return jsonify({'message': 'Rating must be between 1 and 5'}), 400

    existing = db['ratings'].find_one({'email': email, 'book_title': book_title})

    if existing:
        db['ratings'].update_one(
            {'email': email, 'book_title': book_title},
            {'$set': {'rating': int(rating)}}
        )
        return jsonify({'message': 'Rating updated', 'updated': True}), 200
    else:
        db['ratings'].insert_one({
            'email':      email,
            'book_title': book_title,
            'rating':     int(rating)
        })
        return jsonify({'message': 'Rating saved', 'updated': False}), 201


@app.route('/get_rating', methods=['GET'])
def get_rating():
    email      = request.args.get('email')
    book_title = request.args.get('book_title')

    if not email or not book_title:
        return jsonify({'rating': None}), 400

    entry = db['ratings'].find_one(
        {'email': email, 'book_title': book_title},
        {'_id': 0, 'rating': 1}
    )

    if entry:
        return jsonify({'rating': entry['rating']}), 200
    return jsonify({'rating': None}), 200


# ALWAYS LAST
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)