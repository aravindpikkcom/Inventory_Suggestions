import json

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()


DATABASE_SCHEMA = """
SQLite database

Table: sales

Columns:

id INTEGER
product_name TEXT
category TEXT
store TEXT
quantity INTEGER
amount REAL
sale_date TEXT

Meaning:

amount = sales revenue in INR
quantity = number of units sold
sale_date = YYYY-MM-DD
"""


def understand_message(message: str, history=None):

    if history is None:
        history = []

    instructions = f"""
You are a friendly AI assistant for a retail analytics application.

You have two responsibilities.

1. CONVERSATION

If the user says things like:

Hi
Hello
Thank you
Who are you?
What can you do?
Help me

respond conversationally.

Set:

intent = conversation

Do NOT generate SQL.


2. ANALYTICS

If the user asks about:

sales
revenue
products
sarees
stores
units sold
trends
monthly performance
top products
lowest products
comparisons

then:

intent = analytics

Generate a safe SQLite SELECT query.


DATABASE:

{DATABASE_SCHEMA}


SQL RULES:

- Only SELECT statements are allowed.
- Only query the sales table.
- Never use INSERT.
- Never use UPDATE.
- Never use DELETE.
- Never use DROP.
- Never use ALTER.
- Never use CREATE.
- Never use ATTACH.
- Never use PRAGMA.
- Revenue means SUM(amount).
- Units sold means SUM(quantity).
- For product reports normally GROUP BY product_name.
- For store reports normally GROUP BY store.
- For monthly reports use SUBSTR(sale_date, 1, 7).
- For ranked results use ORDER BY.
- Prefer LIMIT 20 for ranked lists.
- x_column and y_column MUST exist in the SELECT output.
- Use line charts for time trends.
- Use bar charts for rankings/comparisons.
- Use pie charts only when useful for composition.

For conversational requests:

sql = ""
chart_type = "none"
x_column = ""
y_column = ""

message should contain the conversational response.

For analytics requests:

message should briefly describe what report is being generated.

Do NOT claim numerical results before the database has been queried.
"""

    input_messages = []

    # Include recent chat history
    for item in history[-8:]:

        role = item.get("role")

        content = item.get("content")

        if (
            role in ["user", "assistant"]
            and content
        ):
            input_messages.append({
                "role": role,
                "content": content
            })

    input_messages.append({
        "role": "user",
        "content": message
    })


    response = client.responses.create(

        model="gpt-6-astra",

        instructions=instructions,

        input=input_messages,

        text={
            "format": {
                "type": "json_schema",

                "name": "retail_assistant_response",

                "strict": True,

                "schema": {
                    "type": "object",

                    "properties": {

                        "intent": {
                            "type": "string",
                            "enum": [
                                "conversation",
                                "analytics"
                            ]
                        },

                        "message": {
                            "type": "string"
                        },

                        "title": {
                            "type": "string"
                        },

                        "sql": {
                            "type": "string"
                        },

                        "chart_type": {
                            "type": "string",
                            "enum": [
                                "none",
                                "bar",
                                "line",
                                "pie"
                            ]
                        },

                        "x_column": {
                            "type": "string"
                        },

                        "y_column": {
                            "type": "string"
                        }
                    },

                    "required": [
                        "intent",
                        "message",
                        "title",
                        "sql",
                        "chart_type",
                        "x_column",
                        "y_column"
                    ],

                    "additionalProperties": False
                }
            }
        }
    )

    return json.loads(
        response.output_text
    )