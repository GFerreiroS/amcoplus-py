import os

from dotenv import load_dotenv

from amcoplus import AmcoClient

load_dotenv()

client_kwargs = {
    "login": os.environ["AMCO_LOGIN"],
    "password": os.environ["AMCO_PASSWORD"],
}
if base_url := os.getenv("AMCO_BASE_URL"):
    client_kwargs["base_url"] = base_url
client = AmcoClient(**client_kwargs)
data = client.get("/installations/search", params={"itemsPerPage": -1})
print(len(data["items"]))
