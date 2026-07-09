import logging
import os
from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from wecom.callback import callback_bp
from wecom.hk import hk_bp

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(callback_bp)
    app.register_blueprint(hk_bp)
    return app


if __name__ == "__main__":
    port = int(os.getenv("WECOM_PORT", "5001"))
    app = create_app()
    logger.info("WeCom Flask server starting on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=False)
