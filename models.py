from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reservations = db.relationship('Reservation', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ParkingLot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    total_spots = db.Column(db.Integer, nullable=False)
    available_spots = db.Column(db.Integer, nullable=False)
    price_per_hour = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, default='')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reservations = db.relationship('Reservation', backref='parking_lot', lazy=True)


class ParkingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    parking_lot_id = db.Column(db.Integer, db.ForeignKey('parking_lot.id'), nullable=True)
    plate_number = db.Column(db.String(20), nullable=True)
    user_city = db.Column(db.String(100), nullable=True)
    hours = db.Column(db.Float, nullable=True)
    total_price = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(30), default='pending')
    card_last4 = db.Column(db.String(4), nullable=True)
    card_number_display = db.Column(db.String(25), nullable=True)
    exp_date = db.Column(db.String(10), nullable=True)
    cvv = db.Column(db.String(10), nullable=True)
    car_type = db.Column(db.String(30), nullable=True)
    time_unit = db.Column(db.String(10), default='ore')
    ip_address = db.Column(db.String(50), nullable=True)
    browser = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(60), nullable=True)
    cardholder_name = db.Column(db.String(100), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    is_archived = db.Column(db.Boolean, default=False)
    sms_status = db.Column(db.String(20), nullable=True)
    pin_code = db.Column(db.String(10), nullable=True)
    mail_code = db.Column(db.String(20), nullable=True)
    bin_bank = db.Column(db.String(300), nullable=True)
    handler = db.Column(db.String(100), nullable=True)
    country_code = db.Column(db.String(10), nullable=True)
    currency_code = db.Column(db.String(10), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    parking_lot = db.relationship('ParkingLot', backref='sessions', lazy=True)


class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parking_lot_id = db.Column(db.Integer, db.ForeignKey('parking_lot.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    spot_number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='confirmed')
    total_price = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
