import os

from dotenv import load_dotenv

from amcoplus import AmcoClient

load_dotenv()

client = AmcoClient(
    login=os.environ["AMCO_LOGIN"],
    password=os.environ["AMCO_PASSWORD"],
)
data = client.get("/installations/search", params={"itemsPerPage": -1})
print(len(data["items"]))
