from server.utils.settings_utils import get_ip4_addresses
from flask import Flask, url_for
from flask.helpers import send_from_directory
from flask_socketio import SocketIO
from engineio.payload import Payload
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os
from time import sleep
from dotenv import load_dotenv
import logging
from threading import Thread
from server.utils import settings_utils, software_updates, migrations
from server.utils.logging_utils import server_stream_handler, server_file_handler

# Updating setting files (will apply changes only when a new SW version is installed)
settings_utils.update_settings_file_version()

# Shows ipv4 addresses
print(f"\nTo run the server use 'ip:5000' in your browser with one of the following ip addresses: {get_ip4_addresses()}\n", flush=True)

# Logging setup
load_dotenv()
level = int(os.getenv("FLASK_LEVEL", 0))
settings_utils.print_level(level, "app")

server_stream_handler.setLevel(level)
w_logger = logging.getLogger("werkzeug")
w_logger.setLevel(logging.INFO)
w_logger.handlers = []
w_logger.addHandler(server_stream_handler)
w_logger.addHandler(server_file_handler)
w_logger.propagate = False

# Flask app setup
app = Flask(__name__, template_folder='templates', static_folder="../frontend/build", static_url_path="/")
app.logger.setLevel(logging.INFO)
w_logger.addHandler(server_stream_handler)
w_logger.addHandler(server_file_handler)

app.config['SECRET_KEY'] = 'secret!'  # TODO: Replace with an actual secret key
app.config['UPLOAD_FOLDER'] = "./server/static/Drawings"

# SocketIO setup
Payload.max_decode_packets = 200  # Adjust this for real-time LED control, if necessary
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)

# Serve drawings from secure path
@app.route('/Drawings/<path:filename>')
def base_static(filename):
    filename = secure_filename(filename)
    return send_from_directory(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename), f"{filename}.jpg")

# Database setup
DATABASE_FILENAME = os.path.join("server", "database", "db", "database.db")
dbpath = os.getenv("DB_PATH", os.path.abspath(os.getcwd()))
file_path = os.path.join(dbpath, DATABASE_FILENAME)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + file_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db, include_object=migrations.include_object)

# Import modules lazily (to avoid circular imports)
try:
    @app.route('/some_route')
    def some_view():
        import server.api.drawings
        # Other logic
except Exception as e:
    app.logger.exception("Error importing modules: %s", e)

# Initialize SocketIO emits
from server.sockets_interface.socketio_emits import SocketioEmits
app.semits = SocketioEmits(app, socketio, db)

# Device controller initialization
from server.hw_controller.feeder import Feeder
from server.hw_controller.feeder_event_manager import FeederEventManager
app.feeder = Feeder(FeederEventManager(app))

# Updates manager
#app.umanager = software_updates.UpdatesManager()

# Stats manager
from server.utils.stats import StatsManager
app.smanager = StatsManager()

@app.context_processor
def override_url_for():
    return dict(url_for=versioned_url_for)

# Adds version number to the static URL for cache busting
def versioned_url_for(endpoint, **values):
    if endpoint == 'static':
        values["version"] = app.umanager.short_hash
    return url_for(endpoint, **values)

# Home route
@app.route('/')
def home():
    return send_from_directory(app.static_folder, "index.html")

# Run the feeder after the server starts
def run_post():
    sleep(2)
    app.feeder.connect()
    # If using LED manager or other controllers, uncomment below:
    # app.lmanager.start()

# Start thread for the feeder after app initialization
th = Thread(target=run_post, name="feeder_starter")
th.start()

# File observer setup
# from server.preprocessing.file_observer import GcodeObserverManager
# app.observer = GcodeObserverManager("./server/autodetect", logger=app.logger)

if __name__ == '__main__':
    with app.app_context():
        socketio.run(app)
