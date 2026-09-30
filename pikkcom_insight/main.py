from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sqlite3


app = FastAPI(
    title="Retail Intelligence API"
)


# Allows frontend to call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


class SearchRequest(BaseModel):
    prompt: str


def run_query(sql):

    connection = sqlite3.connect("retail.db")

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


def understand_prompt(prompt):

    prompt = prompt.lower()


    # Highest selling saree
    if (
        "highest" in prompt
        and "sales" in prompt
        and "saree" in prompt
    ):

        return {

            "title": "Highest Selling Sarees",

            "sql": """
                SELECT
                    product_name,
                    SUM(amount) AS total_sales,
                    SUM(quantity) AS units_sold
                FROM sales
                WHERE category = 'Saree'
                GROUP BY product_name
                ORDER BY total_sales DESC
                LIMIT 10
            """,

            "chart_type": "bar",

            "x": "product_name",

            "y": "total_sales"
        }


    # Top sarees
    if (
        "top" in prompt
        and "saree" in prompt
    ):

        return {

            "title": "Top Sarees",

            "sql": """
                SELECT
                    product_name,
                    SUM(amount) AS total_sales,
                    SUM(quantity) AS units_sold
                FROM sales
                WHERE category = 'Saree'
                GROUP BY product_name
                ORDER BY total_sales DESC
                LIMIT 5
            """,

            "chart_type": "bar",

            "x": "product_name",

            "y": "total_sales"
        }


    # Store sales
    if (
        "store" in prompt
        and (
            "sales" in prompt
            or "revenue" in prompt
        )
    ):

        return {

            "title": "Sales By Store",

            "sql": """
                SELECT
                    store,
                    SUM(amount) AS total_sales,
                    SUM(quantity) AS units_sold
                FROM sales
                GROUP BY store
                ORDER BY total_sales DESC
            """,

            "chart_type": "bar",

            "x": "store",

            "y": "total_sales"
        }


    # Monthly sales
    if "month" in prompt:

        return {

            "title": "Monthly Sales",

            "sql": """
                SELECT
                    SUBSTR(sale_date, 1, 7) AS month,
                    SUM(amount) AS total_sales
                FROM sales
                GROUP BY SUBSTR(sale_date, 1, 7)
                ORDER BY month
            """,

            "chart_type": "line",

            "x": "month",

            "y": "total_sales"
        }


    # Default report
    return {

        "title": "Overall Sales",

        "sql": """
            SELECT
                product_name,
                SUM(amount) AS total_sales,
                SUM(quantity) AS units_sold
            FROM sales
            GROUP BY product_name
            ORDER BY total_sales DESC
            LIMIT 10
        """,

        "chart_type": "bar",

        "x": "product_name",

        "y": "total_sales"
    }


@app.get("/")
def root():

    return {
        "message": "Retail Intelligence API running"
    }


@app.get("/health")
def health():

    return {
        "status": "ok"
    }


@app.post("/search")
def search(request: SearchRequest):

    prompt = request.prompt.strip()

    if not prompt:

        raise HTTPException(
            status_code=400,
            detail="Prompt cannot be empty"
        )


    intent = understand_prompt(prompt)


    rows = run_query(
        intent["sql"]
    )


    if not rows:

        return {

            "answer": "No matching data found.",

            "title": intent["title"],

            "rows": [],

            "chart": None
        }


    first_row = rows[0]


    if "product_name" in first_row:

        answer = (
            f"{first_row['product_name']} has the highest sales "
            f"with ₹{first_row['total_sales']:,.0f} "
            f"and {first_row['units_sold']} units sold."
        )


    elif "store" in first_row:

        answer = (
            f"{first_row['store']} has the highest sales "
            f"with ₹{first_row['total_sales']:,.0f} "
            f"and {first_row['units_sold']} units sold."
        )


    else:

        answer = "Report generated successfully."


    return {

        "answer": answer,

        "title": intent["title"],

        "rows": rows,

        "chart": {

            "type": intent["chart_type"],

            "x": intent["x"],

            "y": intent["y"]
        }
    }