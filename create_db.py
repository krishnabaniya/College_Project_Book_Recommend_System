from flask import Flask
from models import db, User  # तिमीको model.py बाट import गर्दै

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'  # SQLite DB फाइल
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()
    print("✅ Database created with user table and all columns.")
