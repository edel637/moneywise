
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict
from email.parser import BytesParser
from email.policy import default
import sqlite3
import html
import csv
import io
import json
import traceback

# ==========================================
# MONEYWISE SETTINGS
# ==========================================

HOST = "127.0.0.1"
PORT = 5000
DATABASE = Path(__file__).with_name("moneywise_simple.db")

CATEGORIES = [
    "Food", "Transport", "Shopping", "Bills",
    "Entertainment", "Health", "Education",
    "Housing", "Other"
]


# ==========================================
# DATABASE
# ==========================================

def connect_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def setup_database():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                transaction_date TEXT NOT NULL,
                category TEXT DEFAULT 'Other'
            )
        """)

        columns = [
            row["name"]
            for row in db.execute("PRAGMA table_info(transactions)")
        ]

        if "category" not in columns:
            db.execute(
                "ALTER TABLE transactions ADD COLUMN category TEXT DEFAULT 'Other'"
            )

        db.execute("""
            CREATE TABLE IF NOT EXISTS savings_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                target REAL NOT NULL,
                saved REAL NOT NULL DEFAULT 0
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS savings_deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                deposit_date TEXT NOT NULL,
                FOREIGN KEY(goal_id) REFERENCES savings_goals(id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                month TEXT NOT NULL,
                amount REAL NOT NULL,
                UNIQUE(category, month)
            )
        """)


# ==========================================
# GENERAL HELPERS
# ==========================================

def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def money(value):
    return "$" + format(float(value or 0), ",.2f")


def number(value):
    try:
        result = float(value)

        if result <= 0 or result != result:
            return None

        if result == float("inf") or result == float("-inf"):
            return None

        return result

    except (TypeError, ValueError):
        return None


def valid_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except (ValueError, TypeError):
        return None


def current_month():
    return date.today().strftime("%Y-%m")


def month_name(month):
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    except (ValueError, TypeError):
        return month


def form_data(handler):
    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length)
    content_type = handler.headers.get("Content-Type", "")

    if "multipart/form-data" in content_type:
        message = (
            f"Content-Type: {content_type}\r\n"
            "MIME-Version: 1.0\r\n\r\n"
        ).encode() + body

        parsed = BytesParser(policy=default).parsebytes(message)
        result = {}

        for part in parsed.iter_parts():
            name = part.get_param(
                "name",
                header="content-disposition"
            )

            if not name:
                continue

            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""

            if filename:
                result[name] = {
                    "filename": filename,
                    "content": payload
                }
            else:
                charset = part.get_content_charset() or "utf-8"
                result[name] = payload.decode(
                    charset,
                    errors="replace"
                )

        return result

    parsed = parse_qs(body.decode("utf-8", errors="replace"))

    return {
        key: values[0]
        for key, values in parsed.items()
    }


def get_value(data, key, default=""):
    value = data.get(key, default)
    return value if isinstance(value, str) else default


def redirect(handler, location="/"):
    handler.send_response(303)
    handler.send_header("Location", location)
    handler.end_headers()


def category_options(selected="Other"):
    output = ""

    for category in CATEGORIES:
        chosen = "selected" if category == selected else ""

        output += (
            f'<option value="{esc(category)}" {chosen}>'
            f'{esc(category)}</option>'
        )

    return output


# ==========================================
# HTML AND DESIGN
# ==========================================

STYLE = """
<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #f4f8f5;
    color: #26352b;
    font-family: Arial, sans-serif;
    font-size: 17px;
}

header {
    background: #167a45;
    color: white;
    padding: 25px 5%;
}

header h1 {
    margin: 0;
    font-size: 32px;
}

header p {
    margin-bottom: 0;
}

nav {
    background: #105f35;
    padding: 14px 5%;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

nav a {
    color: white;
    text-decoration: none;
    padding: 9px 12px;
    border-radius: 6px;
    font-weight: bold;
}

nav a:hover {
    background: #238b55;
}

main {
    max-width: 1200px;
    margin: 25px auto;
    padding: 0 18px;
}

h2 {
    color: #167a45;
    margin-top: 12px;
}

h3 {
    color: #245b3b;
}

.card {
    background: white;
    border-radius: 12px;
    padding: 22px;
    margin-bottom: 20px;
    box-shadow: 0 2px 9px rgba(0,0,0,0.06);
}

.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px;
}

.stat {
    background: white;
    padding: 22px;
    border-radius: 12px;
    border-left: 6px solid #198754;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}

.stat small {
    color: #647268;
    font-size: 15px;
}

.stat strong {
    display: block;
    font-size: 27px;
    margin-top: 10px;
    overflow-wrap: anywhere;
}

.green {
    color: #168044;
}

.red {
    color: #c0392b;
}

input, select, textarea {
    width: 100%;
    padding: 13px;
    margin: 7px 0 15px;
    border: 1px solid #cbd8ce;
    border-radius: 7px;
    font-size: 17px;
    background: white;
}

label {
    font-weight: bold;
}

button, .button {
    display: inline-block;
    border: none;
    border-radius: 7px;
    padding: 12px 18px;
    background: #167a45;
    color: white;
    font-size: 16px;
    cursor: pointer;
    text-decoration: none;
    margin: 3px 0;
}

button:hover, .button:hover {
    background: #105f35;
}

button.danger, .button.danger {
    background: #bd3c32;
}

button.danger:hover, .button.danger:hover {
    background: #922d26;
}

table {
    width: 100%;
    border-collapse: collapse;
    background: white;
}

th, td {
    padding: 12px;
    border-bottom: 1px solid #e4ebe5;
    text-align: left;
}

th {
    background: #eaf4ed;
}

.table-wrap {
    overflow-x: auto;
}

.progress {
    height: 17px;
    background: #e2eae4;
    border-radius: 20px;
    overflow: hidden;
    margin: 10px 0;
}

.progress div {
    height: 100%;
    background: #198754;
}

.progress.warning div {
    background: #e6a23c;
}

.progress.danger div {
    background: #c0392b;
}

.bar-row {
    margin: 15px 0;
}

.bar-label {
    display: flex;
    justify-content: space-between;
    gap: 10px;
}

.bar {
    height: 19px;
    background: #e6eee8;
    border-radius: 20px;
    overflow: hidden;
    margin-top: 6px;
}

.bar div {
    height: 100%;
    background: #198754;
}

.notice {
    padding: 15px;
    border-radius: 8px;
    background: #e9f5ed;
    margin: 12px 0;
}

.notice.warning {
    background: #fff4df;
}

.notice.danger {
    background: #fdebea;
}

.score {
    font-size: 54px;
    font-weight: bold;
    color: #167a45;
}

.muted {
    color: #6b786e;
}

footer {
    text-align: center;
    padding: 25px;
    color: #718075;
}

@media(max-width: 650px) {
    body {
        font-size: 16px;
    }

    header h1 {
        font-size: 27px;
    }

    nav {
        gap: 4px;
    }

    nav a {
        font-size: 14px;
        padding: 8px;
    }

    .stat strong {
        font-size: 23px;
    }

    th, td {
        padding: 9px;
        font-size: 14px;
    }
}
</style>
"""


def page_start(title):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} - MoneyWise</title>
{STYLE}
</head>
<body>
<header>
    <h1>MoneyWise</h1>
    <p>Your money. Your goals. Your future.</p>
</header>
<nav>
    <a href="/">Dashboard</a>
    <a href="/health">Financial Health</a>
    <a href="/reports">Reports</a>
    <a href="/budgets">Budgets</a>
    <a href="/charts">Charts</a>
    <a href="/data">Data Management</a>
</nav>
<main>
"""


def page_end():
    return """
</main>
<footer>MoneyWise - Manage your money wisely.</footer>
</body>
</html>
"""


def send_html(handler, content, status=200):
    body = content.encode("utf-8")

    handler.send_response(status)
    handler.send_header(
        "Content-Type",
        "text/html; charset=utf-8"
    )
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def error_page(message):
    return (
        page_start("Something went wrong")
        + '<div class="card"><h2>Something went wrong</h2>'
        + f"<p>{esc(message)}</p>"
        + "<p><a href='/'>Return to MoneyWise</a></p></div>"
        + page_end()
    )


# ==========================================
# FINANCIAL CALCULATIONS
# ==========================================

def monthly_totals(month):
    with connect_db() as db:
        income = db.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE kind = 'Income'
            AND substr(transaction_date, 1, 7) = ?
        """, (month,)).fetchone()[0]

        expenses = db.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE kind = 'Expense'
            AND substr(transaction_date, 1, 7) = ?
        """, (month,)).fetchone()[0]

    return float(income), float(expenses)


def previous_month(month):
    year, month_number = map(int, month.split("-"))

    if month_number == 1:
        return f"{year - 1}-12"

    return f"{year}-{month_number - 1:02d}"


def financial_health():
    month = current_month()
    previous = previous_month(month)

    income, expenses = monthly_totals(month)
    old_income, old_expenses = monthly_totals(previous)

    balance = income - expenses

    savings_rate = (
        balance / income * 100
        if income > 0 else 0
    )

    savings_rate = max(-100, min(100, savings_rate))

    if income <= 0:
        score = 0
        rating = "Not enough information"
        advice = (
            "Add your income and expenses to calculate "
            "your financial health."
        )
    else:
        score = max(0, min(100, round(50 + savings_rate)))

        if score >= 80:
            rating = "Excellent"
            advice = (
                "Great work! You are keeping a healthy "
                "amount of your income."
            )
        elif score >= 65:
            rating = "Good"
            advice = (
                "You are making progress. Keep watching "
                "your spending."
            )
        elif score >= 50:
            rating = "Fair"
            advice = (
                "Try to increase your savings and review "
                "unnecessary spending."
            )
        else:
            rating = "Needs attention"
            advice = (
                "Your expenses are high compared with your "
                "income. Review your budget."
            )

    if old_expenses > 0:
        change = (
            (expenses - old_expenses) / old_expenses
        ) * 100

        if change > 0:
            spending_message = (
                f"Spending increased by {change:.1f}% "
                "compared with last month."
            )
        elif change < 0:
            spending_message = (
                f"Spending decreased by {abs(change):.1f}% "
                "compared with last month."
            )
        else:
            spending_message = (
                "Your spending is unchanged compared "
                "with last month."
            )

    elif expenses > 0:
        spending_message = (
            "There was no recorded spending in the previous month."
        )
    else:
        spending_message = (
            "No spending has been recorded this month."
        )

    return {
        "month": month,
        "income": income,
        "expenses": expenses,
        "balance": balance,
        "savings_rate": savings_rate,
        "score": score,
        "rating": rating,
        "advice": advice,
        "spending_message": spending_message,
        "previous_month": previous
    }


# ==========================================
# EDIT TRANSACTION PAGE
# ==========================================

def edit_transaction_page(transaction_id):
    with connect_db() as db:
        transaction = db.execute(
            "SELECT * FROM transactions WHERE id = ?",
            (transaction_id,)
        ).fetchone()

    if not transaction:
        return error_page("Transaction not found.")

    category = transaction["category"] or "Other"

    if category not in CATEGORIES:
        category = "Other"

    content = page_start("Edit Transaction")

    content += f"""
    <div class="card">
        <h2>Edit Transaction</h2>
        <p>Change the information below and save your changes.</p>

        <form method="POST" action="/">
            <input type="hidden" name="action"
                   value="update_transaction">

            <input type="hidden" name="id"
                   value="{transaction['id']}">

            <label>Transaction Type</label>
            <select name="kind">
                <option value="Income"
                    {"selected" if transaction["kind"] == "Income" else ""}>
                    Income
                </option>
                <option value="Expense"
                    {"selected" if transaction["kind"] == "Expense" else ""}>
                    Expense
                </option>
            </select>

            <label>Description</label>
            <input name="description"
                   value="{esc(transaction['description'])}"
                   required>

            <label>Amount ($)</label>
            <input type="number"
                   name="amount"
                   min="0.01"
                   step="0.01"
                   value="{esc(transaction['amount'])}"
                   required>

            <label>Category</label>
            <select name="category">
                {category_options(category)}
            </select>

            <label>Date</label>
            <input type="date"
                   name="transaction_date"
                   value="{esc(transaction['transaction_date'])}"
                   required>

            <button type="submit">Save Changes</button>
            <a class="button" href="/">Cancel</a>
        </form>
    </div>
    """

    content += page_end()
    return content


# ==========================================
# DASHBOARD
# ==========================================

def dashboard_page():
    month = current_month()
    income, expenses = monthly_totals(month)
    balance = income - expenses

    with connect_db() as db:
        all_income = db.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions WHERE kind = 'Income'
        """).fetchone()[0]

        all_expenses = db.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions WHERE kind = 'Expense'
        """).fetchone()[0]

        goals = db.execute("""
            SELECT * FROM savings_goals ORDER BY id DESC
        """).fetchall()

        transactions = db.execute("""
            SELECT * FROM transactions
            ORDER BY transaction_date DESC, id DESC
            LIMIT 10
        """).fetchall()

    total_savings = sum(
        float(goal["saved"]) for goal in goals
    )

    content = page_start("Dashboard")
    content += "<h2>Welcome to MoneyWise</h2>"
    content += (
        f"<p class='muted'>Your financial overview for "
        f"{esc(month_name(month))}</p>"
    )

    content += '<div class="grid">'

    stats = [
        ("Total Income", money(all_income), "green"),
        ("Total Expenses", money(all_expenses), "red"),
        ("Savings Goals", money(total_savings), "green"),
        (
            "Available Balance",
            money(all_income - all_expenses),
            "green"
        )
    ]

    for label, value, color in stats:
        content += (
            '<div class="stat">'
            f'<small>{label}</small>'
            f'<strong class="{color}">{value}</strong>'
            '</div>'
        )

    content += "</div>"

    content += """
    <div class="card">
        <h2>This Month</h2>
        <div class="grid">
    """

    content += (
        f'<div><p>Monthly income</p>'
        f'<h3 class="green">{money(income)}</h3></div>'
        f'<div><p>Monthly expenses</p>'
        f'<h3 class="red">{money(expenses)}</h3></div>'
        f'<div><p>Monthly balance</p>'
        f'<h3>{money(balance)}</h3></div>'
    )

    content += """
        </div>
        <p><a class="button" href="/health">
        View Financial Health</a></p>
    </div>
    """

    content += """
    <div class="card">
        <h2>Add a Transaction</h2>
        <div class="grid">
            <div>
                <h3>Add Income</h3>
                <form method="POST" action="/">
                    <input type="hidden" name="action"
                           value="add_transaction">
                    <input type="hidden" name="kind"
                           value="Income">

                    <label>Description</label>
                    <input name="description"
                           required placeholder="e.g. Salary">

                    <label>Amount ($)</label>
                    <input type="number" name="amount"
                           min="0.01" step="0.01" required>

                    <label>Category</label>
                    <select name="category">
    """

    content += category_options()

    content += """
                    </select>

                    <label>Date</label>
                    <input type="date" name="transaction_date"
                           value="DATE_VALUE" required>

                    <button type="submit">Save Income</button>
                </form>
            </div>

            <div>
                <h3>Add Expense</h3>
                <form method="POST" action="/">
                    <input type="hidden" name="action"
                           value="add_transaction">
                    <input type="hidden" name="kind"
                           value="Expense">

                    <label>Description</label>
                    <input name="description"
                           required placeholder="e.g. Groceries">

                    <label>Amount ($)</label>
                    <input type="number" name="amount"
                           min="0.01" step="0.01" required>

                    <label>Category</label>
                    <select name="category">
    """

    content += category_options()

    content += """
                    </select>

                    <label>Date</label>
                    <input type="date" name="transaction_date"
                           value="DATE_VALUE" required>

                    <button type="submit">Save Expense</button>
                </form>
            </div>
        </div>
    </div>
    """

    content = content.replace(
        "DATE_VALUE",
        date.today().isoformat()
    )

    content += """
    <div class="card">
        <h2>Recent Transactions</h2>
        <div class="table-wrap">
        <table>
            <tr>
                <th>Date</th>
                <th>Type</th>
                <th>Description</th>
                <th>Category</th>
                <th>Amount</th>
                <th>Actions</th>
            </tr>
    """

    if transactions:
        for item in transactions:
            color = (
                "green"
                if item["kind"] == "Income"
                else "red"
            )

            content += f"""
            <tr>
                <td>{esc(item['transaction_date'])}</td>
                <td>{esc(item['kind'])}</td>
                <td>{esc(item['description'])}</td>
                <td>{esc(item['category'] or 'Other')}</td>
                <td class="{color}">
                    {money(item['amount'])}
                </td>
                <td>
                    <a class="button"
                       href="/edit?id={item['id']}">Edit</a>

                    <form method="POST" action="/"
                          onsubmit="return confirm('Delete this transaction?')">

                        <input type="hidden" name="action"
                               value="delete_transaction">

                        <input type="hidden" name="id"
                               value="{item['id']}">

                        <button class="danger"
                                type="submit">Delete</button>
                    </form>
                </td>
            </tr>
            """
    else:
        content += """
        <tr>
            <td colspan="6">
                No transactions yet. Add your first income
                or expense above.
            </td>
        </tr>
        """

    content += """
        </table>
        </div>
    </div>
    """

    content += """
    <div class="card">
        <h2>Savings Goals</h2>
        <p><a class="button" href="/budgets">
        Manage Budgets and Savings</a></p>
        <p><a class="button" href="/reports">
        View Reports</a></p>
    """

    if goals:
        for goal in goals:
            target = float(goal["target"])
            saved = float(goal["saved"])

            percent = (
                min(100, saved / target * 100)
                if target else 0
            )

            content += f"""
            <h3>{esc(goal['name'])}</h3>
            <p>{money(saved)} saved out of {money(target)}</p>
            <div class="progress">
                <div style="width:{percent:.1f}%"></div>
            </div>
            <p>{percent:.1f}% complete</p>
            """
    else:
        content += (
            "<p>You have not created any savings goals yet.</p>"
        )

    content += "</div>"
    content += page_end()

    return content


# ==========================================
# FINANCIAL HEALTH PAGE
# ==========================================

def health_page():
    data = financial_health()

    score = data["score"]
    score_color = "green" if score >= 65 else "red"

    content = page_start("Financial Health")

    content += "<h2>Your Financial Health</h2>"

    content += (
        f"<p class='muted'>A monthly overview for "
        f"{esc(month_name(data['month']))}</p>"
    )

    content += f"""
    <div class="card">
        <h2>Financial Health Score</h2>
        <div class="score {score_color}">{score}/100</div>
        <h3>{esc(data['rating'])}</h3>
        <p>{esc(data['advice'])}</p>
        <p class="muted">
            This is a simple MoneyWise indicator based on your
            monthly income and expenses. It is not a credit score
            or professional financial assessment.
        </p>
    </div>

    <div class="grid">
        <div class="stat">
            <small>Monthly Income</small>
            <strong class="green">{money(data['income'])}</strong>
        </div>

        <div class="stat">
            <small>Monthly Expenses</small>
            <strong class="red">{money(data['expenses'])}</strong>
        </div>

        <div class="stat">
            <small>Money Remaining</small>
            <strong>{money(data['balance'])}</strong>
        </div>

        <div class="stat">
            <small>Savings Rate</small>
            <strong>{data['savings_rate']:.1f}%</strong>
        </div>
    </div>

    <div class="card">
        <h2>Monthly Savings Rate</h2>
        <p>
            Your savings rate shows what percentage of your
            income remains after expenses.
        </p>

        <div class="progress">
            <div style="width:{max(0, min(100, data['savings_rate'])):.1f}%"></div>
        </div>

        <h3>{data['savings_rate']:.1f}%</h3>

        <p>
            Calculation: (Income - Expenses) divided by Income,
            multiplied by 100.
        </p>
    </div>

    <div class="card">
        <h2>Spending Trend</h2>
        <p>{esc(data['spending_message'])}</p>
        <p class="muted">
            Compared with {esc(month_name(data['previous_month']))}.
        </p>
    </div>

    <div class="card">
        <h2>MoneyWise Advice</h2>
        <ul>
            <li>Record your income whenever you receive money.</li>
            <li>Record expenses so you understand where your money goes.</li>
            <li>Set realistic savings goals.</li>
            <li>Use monthly budgets to control spending.</li>
            <li>Review your financial health regularly.</li>
        </ul>
    </div>
    """

    content += page_end()
    return content


# ==========================================
# MONTHLY REPORTS
# ==========================================

def reports_page():
    with connect_db() as db:
        rows = db.execute("""
            SELECT substr(transaction_date, 1, 7) AS month,
                   kind,
                   SUM(amount) AS total
            FROM transactions
            GROUP BY month, kind
            ORDER BY month DESC
        """).fetchall()

    totals = defaultdict(
        lambda: {"Income": 0, "Expense": 0}
    )

    for row in rows:
        totals[row["month"]][row["kind"]] = float(row["total"])

    content = page_start("Monthly Reports")
    content += "<h2>Monthly Financial Reports</h2>"

    if not totals:
        content += """
        <div class="card">
            No transactions have been recorded yet.
        </div>
        """
    else:
        content += """
        <div class="card">
        <div class="table-wrap">
        <table>
            <tr>
                <th>Month</th>
                <th>Income</th>
                <th>Expenses</th>
                <th>Balance</th>
            </tr>
        """

        for month in sorted(totals.keys(), reverse=True):
            income = totals[month]["Income"]
            expenses = totals[month]["Expense"]
            balance = income - expenses

            content += f"""
            <tr>
                <td>{esc(month_name(month))}</td>
                <td class="green">{money(income)}</td>
                <td class="red">{money(expenses)}</td>
                <td>{money(balance)}</td>
            </tr>
            """

        content += "</table></div></div>"

    content += page_end()
    return content


# ==========================================
# BUDGET MANAGEMENT AND SAVINGS
# ==========================================

def budgets_page():
    month = current_month()

    with connect_db() as db:
        budgets = db.execute("""
            SELECT * FROM budgets
            WHERE month = ?
            ORDER BY category
        """, (month,)).fetchall()

        goals = db.execute("""
            SELECT * FROM savings_goals
            ORDER BY id DESC
        """).fetchall()

        rows = db.execute("""
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE kind = 'Expense'
            AND substr(transaction_date, 1, 7) = ?
            GROUP BY category
        """, (month,)).fetchall()

    spending = defaultdict(float)

    for row in rows:
        spending[row["category"] or "Other"] = float(row["total"])

    content = page_start("Budgets")
    content += "<h2>Budget Management</h2>"

    content += (
        f"<p class='muted'>Budgets for "
        f"{esc(month_name(month))}</p>"
    )

    content += """
    <div class="card">
        <h3>Create or Update a Monthly Budget</h3>

        <form method="POST" action="/budgets">
            <input type="hidden" name="action"
                   value="save_budget">

            <label>Category</label>
            <select name="category">
    """

    content += category_options()

    content += """
            </select>

            <label>Monthly budget amount ($)</label>
            <input type="number" name="amount"
                   min="0.01" step="0.01" required>

            <button type="submit">Save Budget</button>
        </form>
    </div>
    """

    content += """
    <div class="card">
        <h3>Your Monthly Budgets</h3>
    """

    if budgets:
        for budget in budgets:
            category = budget["category"]
            amount = float(budget["amount"])
            spent = spending[category]
            remaining = amount - spent

            percent = spent / amount * 100 if amount else 0
            width = min(100, percent)

            css_class = ""

            if percent >= 100:
                css_class = "danger"
            elif percent >= 80:
                css_class = "warning"

            warning = ""

            if percent >= 100:
                warning = (
                    '<div class="notice danger">'
                    'You have reached or exceeded this budget.'
                    '</div>'
                )
            elif percent >= 80:
                warning = (
                    '<div class="notice warning">'
                    'You have used at least 80% of this budget.'
                    '</div>'
                )

            content += f"""
            <h3>{esc(category)}</h3>
            <p>
                Budget: {money(amount)} |
                Spent: {money(spent)}
            </p>
            <p>
                Remaining: <strong>{money(remaining)}</strong>
            </p>

            <div class="progress {css_class}">
                <div style="width:{width:.1f}%"></div>
            </div>

            <p>{percent:.1f}% used</p>
            {warning}
            """
    else:
        content += (
            "<p>You have not created any budgets for this month.</p>"
        )

    content += "</div>"

    content += """
    <div class="card">
        <h2>Savings Goals</h2>

        <form method="POST" action="/budgets">
            <input type="hidden" name="action"
                   value="add_goal">

            <label>Goal name</label>
            <input name="name" required
                   placeholder="e.g. New laptop">

            <label>Target amount ($)</label>
            <input type="number" name="target"
                   min="0.01" step="0.01" required>

            <button type="submit">Create Savings Goal</button>
        </form>
    </div>
    """

    content += """
    <div class="card">
        <h3>Your Savings Goals</h3>
    """

    if goals:
        for goal in goals:
            target = float(goal["target"])
            saved = float(goal["saved"])

            percent = (
                min(100, saved / target * 100)
                if target else 0
            )

            content += f"""
            <h3>{esc(goal['name'])}</h3>
            <p>
                Saved: {money(saved)} /
                Target: {money(target)}
            </p>

            <div class="progress">
                <div style="width:{percent:.1f}%"></div>
            </div>

            <p>{percent:.1f}% complete</p>

            <form method="POST" action="/budgets">
                <input type="hidden" name="action"
                       value="deposit">

                <input type="hidden" name="goal_id"
                       value="{goal['id']}">

                <label>Deposit amount ($)</label>
                <input type="number" name="amount"
                       min="0.01" step="0.01" required>

                <button type="submit">Add Savings</button>
            </form>

            <form method="POST" action="/budgets"
                  onsubmit="return confirm('Delete this savings goal?')">

                <input type="hidden" name="action"
                       value="delete_goal">

                <input type="hidden" name="goal_id"
                       value="{goal['id']}">

                <button class="danger" type="submit">
                    Delete Goal
                </button>
            </form>

            <hr>
            """
    else:
        content += (
            "<p>No savings goals yet. Create your first goal above.</p>"
        )

    content += "</div>"
    content += page_end()

    return content


# ==========================================
# SPENDING CHARTS
# ==========================================

def charts_page():
    month = current_month()
    income, expenses = monthly_totals(month)

    with connect_db() as db:
        categories = db.execute("""
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE kind = 'Expense'
            AND substr(transaction_date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
        """, (month,)).fetchall()

        monthly = db.execute("""
            SELECT substr(transaction_date, 1, 7) AS month,
                   kind,
                   SUM(amount) AS total
            FROM transactions
            GROUP BY month, kind
            ORDER BY month DESC
            LIMIT 24
        """).fetchall()

    month_totals = defaultdict(
        lambda: {"Income": 0, "Expense": 0}
    )

    for row in monthly:
        month_totals[row["month"]][row["kind"]] = float(row["total"])

    max_category = max(
        [float(row["total"]) for row in categories],
        default=1
    )

    content = page_start("Spending Charts")
    content += "<h2>Spending Charts</h2>"

    content += (
        f"<p class='muted'>Showing data for "
        f"{esc(month_name(month))}</p>"
    )

    content += "<div class='card'><h3>Income vs Expenses</h3>"

    maximum = max(income, expenses, 1)

    content += f"""
    <div class="bar-row">
        <div class="bar-label">
            <strong>Income</strong>
            <span>{money(income)}</span>
        </div>
        <div class="bar">
            <div style="width:{income / maximum * 100:.1f}%"></div>
        </div>
    </div>

    <div class="bar-row">
        <div class="bar-label">
            <strong>Expenses</strong>
            <span>{money(expenses)}</span>
        </div>
        <div class="bar">
            <div style="width:{expenses / maximum * 100:.1f}%"></div>
        </div>
    </div>
    </div>
    """

    content += "<div class='card'><h3>Spending by Category</h3>"

    if categories:
        for row in categories:
            total = float(row["total"])
            width = total / max_category * 100

            content += f"""
            <div class="bar-row">
                <div class="bar-label">
                    <strong>{esc(row['category'] or 'Other')}</strong>
                    <span>{money(total)}</span>
                </div>

                <div class="bar">
                    <div style="width:{width:.1f}%"></div>
                </div>
            </div>
            """
    else:
        content += "<p>No expenses recorded this month.</p>"

    content += "</div>"

    content += """
    <div class="card">
        <h3>Monthly Income and Expenses</h3>
    """

    if month_totals:
        for month_key in sorted(month_totals.keys(), reverse=True):
            values = month_totals[month_key]

            content += f"""
            <h3>{esc(month_name(month_key))}</h3>
            <p class="green">
                Income: {money(values['Income'])}
            </p>
            <p class="red">
                Expenses: {money(values['Expense'])}
            </p>
            <hr>
            """

    content += "</div>"

    content += """
    <div class="card">
        <h3>MoneyWise Advice</h3>
        <p>
            Check your category spending regularly. If one category
            is taking too much of your money, consider setting a
            budget for it.
        </p>
    </div>
    """

    content += page_end()
    return content


# ==========================================
# DATA MANAGEMENT
# ==========================================

def data_page():
    content = page_start("Data Management")

    content += """
    <h2>Data Management</h2>

    <div class="card">
        <h3>Export Transactions</h3>
        <p>
            Download your transaction history as a CSV spreadsheet.
        </p>
        <a class="button" href="/export.csv">Download CSV</a>
    </div>

    <div class="card">
        <h3>Download Full Backup</h3>
        <p>
            Save a backup of your MoneyWise data as a JSON file.
        </p>
        <a class="button" href="/backup">Download Backup</a>
    </div>

    <div class="card">
        <h3>Restore a Backup</h3>
        <p>
            Restore your MoneyWise information from a JSON backup.
        </p>

        <p>
            <strong>Warning:</strong> Restoring replaces the current
            transactions, budgets and savings information.
            Download a backup first.
        </p>

        <form method="POST" action="/data"
              enctype="multipart/form-data">

            <input type="hidden" name="action" value="restore">

            <label>Select your JSON backup</label>
            <input type="file" name="backup_file"
                   accept=".json,application/json" required>

            <button type="submit" class="danger"
                onclick="return confirm('Restore this backup? Current data will be replaced.')">
                Restore Backup
            </button>
        </form>
    </div>
    """

    content += page_end()
    return content


def send_download(handler, filename, content, content_type):
    body = (
        content
        if isinstance(content, bytes)
        else content.encode("utf-8")
    )

    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header(
        "Content-Disposition",
        f'attachment; filename="{filename}"'
    )
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def export_csv(handler):
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID", "Type", "Description",
        "Amount", "Date", "Category"
    ])

    with connect_db() as db:
        rows = db.execute("""
            SELECT id, kind, description, amount,
                   transaction_date, category
            FROM transactions
            ORDER BY transaction_date DESC, id DESC
        """).fetchall()

    for row in rows:
        writer.writerow([
            row["id"],
            row["kind"],
            row["description"],
            row["amount"],
            row["transaction_date"],
            row["category"]
        ])

    send_download(
        handler,
        "moneywise_transactions.csv",
        "\ufeff" + output.getvalue(),
        "text/csv; charset=utf-8"
    )


def export_backup(handler):
    backup = {}

    with connect_db() as db:
        for table in [
            "transactions",
            "savings_goals",
            "savings_deposits",
            "budgets"
        ]:
            rows = db.execute(
                f"SELECT * FROM {table}"
            ).fetchall()

            backup[table] = [dict(row) for row in rows]

    backup["moneywise_backup_version"] = 1

    content = json.dumps(backup, indent=2)

    send_download(
        handler,
        "moneywise_backup.json",
        content,
        "application/json; charset=utf-8"
    )


def restore_backup(upload):
    if not isinstance(upload, dict):
        raise ValueError("Please select a backup file.")

    if not upload.get("filename", "").lower().endswith(".json"):
        raise ValueError("The backup must be a JSON file.")

    raw = upload.get("content", b"")

    if not raw:
        raise ValueError("The selected backup file is empty.")

    backup = json.loads(raw.decode("utf-8"))

    required_tables = [
        "transactions",
        "savings_goals",
        "savings_deposits",
        "budgets"
    ]

    for table in required_tables:
        if table not in backup or not isinstance(backup[table], list):
            raise ValueError(
                f"The backup is missing valid {table} data."
            )

    with connect_db() as db:
        db.execute("BEGIN")

        db.execute("DELETE FROM savings_deposits")
        db.execute("DELETE FROM savings_goals")
        db.execute("DELETE FROM transactions")
        db.execute("DELETE FROM budgets")

        for row in backup["transactions"]:
            if row.get("kind") not in ("Income", "Expense"):
                raise ValueError("A transaction has an invalid type.")

            amount = number(row.get("amount"))
            transaction_date = valid_date(
                row.get("transaction_date")
            )

            if amount is None or not transaction_date:
                raise ValueError(
                    "A transaction has an invalid amount or date."
                )

            description = str(row.get("description", "")).strip()

            if not description:
                raise ValueError(
                    "A transaction has an empty description."
                )

            category = row.get("category") or "Other"

            if category not in CATEGORIES:
                category = "Other"

            db.execute("""
                INSERT INTO transactions
                (id, kind, description, amount,
                 transaction_date, category)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                row.get("id"),
                row["kind"],
                description,
                amount,
                transaction_date,
                category
            ))

        for row in backup["savings_goals"]:
            target = number(row.get("target"))

            try:
                saved = float(row.get("saved", 0))
            except (TypeError, ValueError):
                saved = -1

            if target is None or saved < 0:
                raise ValueError(
                    "A savings goal has invalid amounts."
                )

            name = str(row.get("name", "")).strip()

            if not name:
                raise ValueError("A savings goal has no name.")

            db.execute("""
                INSERT INTO savings_goals
                (id, name, target, saved)
                VALUES (?, ?, ?, ?)
            """, (
                row.get("id"),
                name,
                target,
                saved
            ))

        for row in backup["savings_deposits"]:
            amount = number(row.get("amount"))
            deposit_date = valid_date(row.get("deposit_date"))

            if amount is None or not deposit_date:
                raise ValueError(
                    "A savings deposit has invalid information."
                )

            db.execute("""
                INSERT INTO savings_deposits
                (id, goal_id, amount, deposit_date)
                VALUES (?, ?, ?, ?)
            """, (
                row.get("id"),
                row.get("goal_id"),
                amount,
                deposit_date
            ))

        for row in backup["budgets"]:
            amount = number(row.get("amount"))
            budget_month = row.get("month")
            category = row.get("category", "Other")

            if amount is None:
                raise ValueError("A budget has an invalid amount.")

            try:
                datetime.strptime(budget_month, "%Y-%m")
            except (ValueError, TypeError):
                raise ValueError("A budget has an invalid month.")

            if category not in CATEGORIES:
                category = "Other"

            db.execute("""
                INSERT INTO budgets
                (id, category, month, amount)
                VALUES (?, ?, ?, ?)
            """, (
                row.get("id"),
                category,
                budget_month,
                amount
            ))


# ==========================================
# REQUEST HANDLER
# ==========================================

class MoneyWiseHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        try:
            if path == "/":
                send_html(self, dashboard_page())

            elif path == "/edit":
                query = parse_qs(urlparse(self.path).query)

                try:
                    transaction_id = int(
                        query.get("id", ["0"])[0]
                    )
                except ValueError:
                    raise ValueError("Invalid transaction ID.")

                send_html(
                    self,
                    edit_transaction_page(transaction_id)
                )

            elif path == "/health":
                send_html(self, health_page())

            elif path == "/reports":
                send_html(self, reports_page())

            elif path == "/budgets":
                send_html(self, budgets_page())

            elif path == "/charts":
                send_html(self, charts_page())

            elif path == "/data":
                send_html(self, data_page())

            elif path == "/export.csv":
                export_csv(self)

            elif path == "/backup":
                export_backup(self)

            else:
                send_html(
                    self,
                    error_page("The page you requested was not found."),
                    404
                )

        except Exception as error:
            traceback.print_exc()

            try:
                send_html(
                    self,
                    error_page(str(error)),
                    500
                )
            except Exception:
                pass

    def do_POST(self):
        try:
            data = form_data(self)
            action = get_value(data, "action")

            # ADD TRANSACTION
            if action == "add_transaction":
                kind = get_value(data, "kind")
                description = get_value(data, "description").strip()
                amount = number(get_value(data, "amount"))

                transaction_date = valid_date(
                    get_value(data, "transaction_date")
                )

                category = get_value(data, "category", "Other")

                if kind not in ("Income", "Expense"):
                    raise ValueError(
                        "Please select a valid transaction type."
                    )

                if not description:
                    raise ValueError("Please enter a description.")

                if amount is None:
                    raise ValueError(
                        "Please enter a valid amount greater than zero."
                    )

                if not transaction_date:
                    raise ValueError("Please enter a valid date.")

                if category not in CATEGORIES:
                    category = "Other"

                with connect_db() as db:
                    db.execute("""
                        INSERT INTO transactions
                        (kind, description, amount,
                         transaction_date, category)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        kind,
                        description,
                        amount,
                        transaction_date,
                        category
                    ))

                redirect(self, "/")
                return

            # EDIT / UPDATE TRANSACTION
            elif action == "update_transaction":
                try:
                    transaction_id = int(
                        get_value(data, "id")
                    )
                except ValueError:
                    raise ValueError("Invalid transaction ID.")

                kind = get_value(data, "kind")
                description = get_value(data, "description").strip()
                amount = number(get_value(data, "amount"))

                transaction_date = valid_date(
                    get_value(data, "transaction_date")
                )

                category = get_value(data, "category", "Other")

                if kind not in ("Income", "Expense"):
                    raise ValueError(
                        "Please select a valid transaction type."
                    )

                if not description:
                    raise ValueError("Please enter a description.")

                if amount is None:
                    raise ValueError("Please enter a valid amount.")

                if not transaction_date:
                    raise ValueError("Please enter a valid date.")

                if category not in CATEGORIES:
                    category = "Other"

                with connect_db() as db:
                    existing = db.execute(
                        "SELECT id FROM transactions WHERE id = ?",
                        (transaction_id,)
                    ).fetchone()

                    if not existing:
                        raise ValueError("Transaction not found.")

                    db.execute("""
                        UPDATE transactions
                        SET kind = ?,
                            description = ?,
                            amount = ?,
                            transaction_date = ?,
                            category = ?
                        WHERE id = ?
                    """, (
                        kind,
                        description,
                        amount,
                        transaction_date,
                        category,
                        transaction_id
                    ))

                redirect(self, "/")
                return

            # DELETE TRANSACTION
            elif action == "delete_transaction":
                try:
                    transaction_id = int(
                        get_value(data, "id")
                    )
                except ValueError:
                    raise ValueError("Invalid transaction ID.")

                with connect_db() as db:
                    db.execute(
                        "DELETE FROM transactions WHERE id = ?",
                        (transaction_id,)
                    )

                redirect(self, "/")
                return

            # SAVE BUDGET
            elif action == "save_budget":
                category = get_value(data, "category")
                amount = number(get_value(data, "amount"))

                if category not in CATEGORIES or amount is None:
                    raise ValueError(
                        "Please enter a valid category and budget amount."
                    )

                with connect_db() as db:
                    db.execute("""
                        INSERT INTO budgets (category, month, amount)
                        VALUES (?, ?, ?)
                        ON CONFLICT(category, month)
                        DO UPDATE SET amount = excluded.amount
                    """, (
                        category,
                        current_month(),
                        amount
                    ))

                redirect(self, "/budgets")
                return

            # ADD SAVINGS GOAL
            elif action == "add_goal":
                name = get_value(data, "name").strip()
                target = number(get_value(data, "target"))

                if not name or target is None:
                    raise ValueError(
                        "Please enter a goal name and valid target amount."
                    )

                with connect_db() as db:
                    db.execute("""
                        INSERT INTO savings_goals
                        (name, target, saved)
                        VALUES (?, ?, 0)
                    """, (name, target))

                redirect(self, "/budgets")
                return

            # DEPOSIT INTO SAVINGS GOAL
            elif action == "deposit":
                try:
                    goal_id = int(get_value(data, "goal_id"))
                except ValueError:
                    raise ValueError("Invalid savings goal.")

                amount = number(get_value(data, "amount"))

                if amount is None:
                    raise ValueError(
                        "Please enter a valid deposit amount."
                    )

                with connect_db() as db:
                    goal = db.execute(
                        "SELECT id FROM savings_goals WHERE id = ?",
                        (goal_id,)
                    ).fetchone()

                    if not goal:
                        raise ValueError("Savings goal not found.")

                    db.execute("""
                        UPDATE savings_goals
                        SET saved = saved + ?
                        WHERE id = ?
                    """, (amount, goal_id))

                    db.execute("""
                        INSERT INTO savings_deposits
                        (goal_id, amount, deposit_date)
                        VALUES (?, ?, ?)
                    """, (
                        goal_id,
                        amount,
                        date.today().isoformat()
                    ))

                redirect(self, "/budgets")
                return

            # DELETE SAVINGS GOAL
            elif action == "delete_goal":
                try:
                    goal_id = int(get_value(data, "goal_id"))
                except ValueError:
                    raise ValueError("Invalid savings goal.")

                with connect_db() as db:
                    db.execute(
                        "DELETE FROM savings_goals WHERE id = ?",
                        (goal_id,)
                    )

                redirect(self, "/budgets")
                return

            # RESTORE BACKUP
            elif action == "restore":
                restore_backup(data.get("backup_file"))

                send_html(
                    self,
                    page_start("Backup Restored")
                    + """
                    <div class="card">
                        <h2>Backup restored successfully!</h2>
                        <p>Your MoneyWise data has been restored.</p>
                        <p>
                            <a class="button" href="/">
                                Return to Dashboard
                            </a>
                        </p>
                    </div>
                    """
                    + page_end()
                )
                return

            else:
                raise ValueError("Unknown action.")

        except Exception as error:
            traceback.print_exc()

            try:
                send_html(
                    self,
                    error_page(str(error)),
                    400
                )
            except Exception:
                pass


# ==========================================
# START MONEYWISE
# ==========================================

if __name__ == "__main__":
    setup_database()

    server = HTTPServer((HOST, PORT), MoneyWiseHandler)

    print("-------------------------------------")
    print("       MONEYWISE IS RUNNING")
    print("-------------------------------------")
    print(f"Open your browser at: http://{HOST}:{PORT}")
    print("Press CTRL + C to stop the server.")

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print("\nMoneyWise server stopped.")

    finally:
        server.server_close()
