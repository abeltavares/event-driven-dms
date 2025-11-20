import random

from locust import HttpUser, between, task


class DocumentUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """Initialize: Create some documents for this user."""
        self.document_ids = []

        # Create 3 documents per user
        for i in range(3):
            try:
                response = self.client.post(
                    "/documents",
                    json={
                        "title": f"Init Document {i}",
                        "content": "Initial document for testing",
                        "created_by": f"user{random.randint(1, 100)}@test.com",  # noqa: S311
                    },
                )
                if response.status_code == 201:
                    self.document_ids.append(response.json()["id"])
            except Exception:
                pass  # Ignore initialization errors

    @task(5)  # 50% - Most common: Read documents
    def list_documents(self):
        """List all documents."""
        self.client.get("/documents")

    @task(3)  # 30% - Create new document
    def create_document(self):
        """Create a document."""
        self.client.post(
            "/documents",
            json={
                "title": f"Test Document {random.randint(1, 10000)}",  # noqa: S311
                "content": "Load test content for performance testing",
                "created_by": f"user{random.randint(1, 100)}@test.com",  # noqa: S311
            },
        )

    @task(2)  # 20% - Search
    def search_documents(self):
        """Search documents."""
        queries = ["test", "document", "contract", "sales", "agreement"]
        query = random.choice(queries)  # noqa: S311
        self.client.get(f"/search?q={query}&size=10")

    @task(1)  # 10% - Sign document
    def sign_document(self):
        """Sign a document."""
        if self.document_ids:
            doc_id = random.choice(self.document_ids)  # noqa: S311
            self.client.post(
                "/signatures",
                json={
                    "document_id": doc_id,
                    "signer_email": f"signer{random.randint(1, 50)}@test.com",  # noqa: S311
                    "signer_name": f"Signer {random.randint(1, 50)}",  # noqa: S311
                    "signature_data": "base64encodedimage==",
                },
            )
        else:
            # Fallback: Get any document
            response = self.client.get("/documents")
            if response.status_code == 200:
                docs = response.json()
                if docs:
                    doc_id = docs[0]["id"]
                    self.client.post(
                        "/signatures",
                        json={
                            "document_id": doc_id,
                            "signer_email": "signer@test.com",
                            "signer_name": "Load Tester",
                            "signature_data": "test",
                        },
                    )


class SearchUser(HttpUser):
    """User that only searches (simulates analytics/reporting)."""

    wait_time = between(0.5, 2)
    weight = 1  # 1 SearchUser for every 3 DocumentUsers

    @task(10)
    def search(self):
        """Heavy search user."""
        queries = ["test", "document", "contract", "sales", "agreement", "Q4", "2025"]
        query = random.choice(queries)  # noqa: S311
        self.client.get(f"/search?q={query}&size=20")

    @task(1)
    def list_documents(self):
        """Occasionally list documents."""
        self.client.get("/documents")
