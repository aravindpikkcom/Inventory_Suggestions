import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_service import understand_message


app = FastAPI(
    title="Retail AI Assistant"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


class HistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[HistoryItem] = []


FORBIDDEN_SQL_WORDS = [
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "pragma",
    "attach",
    "detach",
    "replace"
]


def validate_sql(sql: str):

    normalized = (
        sql
        .strip()
        .lower()
    )

    if not normalized.startswith("select"):

        raise ValueError(
            "Only SELECT queries are permitted."
        )


    # Prevent multiple SQL statements
    cleaned = normalized.rstrip(";")

    if ";" in cleaned:

        raise ValueError(
            "Multiple SQL statements are not permitted."
        )


    for word in FORBIDDEN_SQL_WORDS:

        if word in normalized.split():

            raise ValueError(
                f"Forbidden SQL operation detected: {word}"
            )


    if " sales" not in normalized:

        raise ValueError(
            "Only the sales table may be queried."
        )


def execute_query(sql: str):

    validate_sql(sql)

    connection = sqlite3.connect(
        "retail.db"
    )

    connection.row_factory = sqlite3.Row

    try:

        cursor = connection.cursor()

        cursor.execute(sql)

        rows = cursor.fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:

        connection.close()


def format_number(
    column_name,
    value
):

    column = column_name.lower()

    if isinstance(
        value,
        (int, float)
    ):

        if any(
            keyword in column
            for keyword in [
                "sales",
                "revenue",
                "amount"
            ]
        ):

            return (
                f"₹{value:,.0f}"
            )

        return f"{value:,.0f}"

    return str(value)


def build_analytics_answer(
    plan,
    rows
):

    if not rows:

        return (
            "I couldn't find any matching data "
            "for that request."
        )


    x_column = plan["x_column"]

    y_column = plan["y_column"]


    first = rows[0]


    if (
        x_column in first
        and y_column in first
    ):

        name = first[x_column]

        value = format_number(
            y_column,
            first[y_column]
        )


        if plan["chart_type"] == "line":

            return (
                f"I generated the {plan['title']} report. "
                f"You can see the trend in the chart and "
                f"the detailed values in the table below."
            )


        return (
            f"{name} is the top result with {value}. "
            f"I've included the complete report below."
        )


    return (
        f"I generated the {plan['title']} report."
    )


@app.get("/")
def root():

    return {
        "message":
            "Retail AI Assistant API is running."
    }


@app.get("/health")
def health():

    return {
        "status": "ok"
    }


@app.post("/chat")
def chat(
    request: ChatRequest
):

    message = request.message.strip()

    if not message:

        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty."
        )


    try:

        history = [
            item.model_dump()
            for item in request.history
        ]


        # Ask OpenAI what kind of request this is
        plan = understand_message(
            message,
            history
        )


        print("\nAI PLAN")
        print(plan)


        # Normal conversation
        if plan["intent"] == "conversation":

            return {

                "type": "conversation",

                "message":
                    plan["message"],

                "title": "",

                "rows": [],

                "chart": None

            }


        # Analytics request
        sql = plan["sql"]


        print("\nGENERATED SQL")
        print(sql)


        rows = execute_query(sql)


        assistant_answer = (
            build_analytics_answer(
                plan,
                rows
            )
        )


        return {

            "type":
                "analytics",

            "message":
                assistant_answer,

            "title":
                plan["title"],

            "rows":
                rows,

            "chart": {

                "type":
                    plan["chart_type"],

                "x":
                    plan["x_column"],

                "y":
                    plan["y_column"]

            },

            # Keep this during development.
            # You may remove it in production.
            "sql":
                sql
        }


    except Exception as error:

        print(
            "\nERROR:",
            str(error)
        )


        raise HTTPException(
            status_code=500,
            detail=str(error)
        )