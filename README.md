# ParkFlow Localhost Web App

## Run
1. Install Python 3.10+.
2. In this folder run: `py -m pip install -r requirements.txt`
3. Run: `py app.py`
4. Open: http://localhost:5000

Login: `admin`
Password: `parkflow`

The application creates `parking.db` automatically.

The complete flow is browser based: login -> dashboard -> plate registration -> QR -> animated entry -> occupied space -> exit QR -> timer/bill -> payment -> space released.

Demo mode uses a 10-second grace period. Set `DEMO_MODE=False` in app.py for the real 2-minute period.
