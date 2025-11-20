# kong-config/configure.py

import logging
import sys
import time

import requests

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

KONG_ADMIN_URL = "http://kong:8001"
STATUS_OK = 200


def wait_for_kong():
    """Wait for Kong to be ready."""
    logger.info("Waiting for Kong...")
    for _ in range(30):
        try:
            r = requests.get(f"{KONG_ADMIN_URL}/status", timeout=5)
            if r.status_code == STATUS_OK:
                logger.info("Kong ready")
                return True
        except Exception:
            pass
        time.sleep(2)
    logger.error("Kong failed to start")
    return False


def create_service(name, url):
    """Create a Kong service."""
    response = requests.post(
        f"{KONG_ADMIN_URL}/services",
        json={
            "name": name,
            "url": url,
            "connect_timeout": 60000,
            "write_timeout": 60000,
            "read_timeout": 60000,
        }
    )
    if response.status_code in [200, 201]:
        logger.info(f"Service '{name}' created")
        return True
    else:
        logger.error(f"Failed to create service '{name}': {response.text}")
        return False


def create_route(service_name, route_name, paths, strip_path=False):
    """Create a Kong route."""
    response = requests.post(
        f"{KONG_ADMIN_URL}/services/{service_name}/routes",
        json={
            "name": route_name,
            "paths": paths,
            "strip_path": strip_path,
        }
    )
    if response.status_code in [200, 201]:
        logger.info(f"Route '{route_name}' created: {paths}")
        return True
    else:
        logger.error(f"✗ Failed to create route '{route_name}': {response.text}")
        return False


def enable_cors(service_name):
    """Enable CORS plugin for a service."""
    response = requests.post(
        f"{KONG_ADMIN_URL}/services/{service_name}/plugins",
        json={
            "name": "cors",
            "config": {
                "origins": ["*"],
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "headers": ["Accept", "Content-Type", "Authorization"],
                "exposed_headers": ["X-Auth-Token"],
                "credentials": True,
                "max_age": 3600,
            }
        }
    )
    if response.status_code in [200, 201]:
        logger.info(f"CORS enabled for '{service_name}'")
        return True
    else:
        logger.error(f"Failed to enable CORS for '{service_name}': {response.text}")
        return False


def setup():
    """Configure Kong Gateway."""
    if not wait_for_kong():
        sys.exit(1)

    logger.info("\n" + "=" * 60)

    logger.info("\n[1/4] Configuring Document Service...")
    create_service("document-service", "http://document-service:8000")
    create_route("document-service", "document-route", ["/documents"], strip_path=False)
    enable_cors("document-service")

    logger.info("\n[2/4] Configuring Signature Service...")
    create_service("signature-service", "http://signature-service:8000")
    create_route("signature-service", "signature-route", ["/signatures"], strip_path=False)
    enable_cors("signature-service")

    logger.info("\n[3/4] Configuring Search Service...")
    create_service("search-service", "http://search-service:8000")
    create_route("search-service", "search-route", ["/search"], strip_path=False)
    create_route("search-service", "aggregations-route", ["/aggregations"], strip_path=False)
    enable_cors("search-service")


    logger.info("\n[4/4] Configuring WebSocket Service...")
    create_service("websocket-service", "http://websocket-service:8000")
    create_route("websocket-service", "ws-route", ["/ws"], strip_path=False)
    create_route("websocket-service", "auth-route", ["/auth"], strip_path=False)
    enable_cors("websocket-service")

    logger.info("\n" + "=" * 60)
    logger.info("Kong Gateway Configuration Complete")
    logger.info("=" * 60)
    logger.info("Available Endpoints:")
    logger.info("  • http://localhost:8000/documents")
    logger.info("  • http://localhost:8000/documents/{id}")
    logger.info("  • http://localhost:8000/documents/{id}/stats")
    logger.info("  • http://localhost:8000/signatures")
    logger.info("  • http://localhost:8000/search?q=...")
    logger.info("  • http://localhost:8000/aggregations/{field}")
    logger.info("  • ws://localhost:8000/ws/{doc_id}?token=...")
    logger.info("  • http://localhost:8000/auth/token?user_id=...")
    logger.info("=" * 60)


if __name__ == "__main__":
    setup()
