import datetime
import decimal
import os
import re

from app.connector_store import get_connector_settings


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
TABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$")
ALLOWED_FILTER_OPS = {"=", ">", "<", ">=", "<=", "like", "in"}



def _text(value):
    return str(value or "").strip()



def _normalize_table_name(value):
    return _text(value).lower()



def _is_valid_identifier(name):
    return bool(IDENTIFIER_PATTERN.match(_text(name)))



def _is_valid_table_name(name):
    return bool(TABLE_PATTERN.match(_text(name)))



def _validate_allowlist(allowlist):
    cleaned = []
    for raw in allowlist or []:
        token = _normalize_table_name(raw)
        if token and _is_valid_table_name(token) and token not in cleaned:
            cleaned.append(token)
    return cleaned



def snowflake_runtime_config(user_id):
    settings = get_connector_settings(user_id, "snowflake_insights")
    allowlist = settings.get("snowflake_table_allowlist") if isinstance(settings.get("snowflake_table_allowlist"), list) else []
    return {
        "account": _text(settings.get("snowflake_account") or os.getenv("SNOWFLAKE_ACCOUNT")),
        "warehouse": _text(settings.get("snowflake_warehouse") or os.getenv("SNOWFLAKE_WAREHOUSE")),
        "database": _text(settings.get("snowflake_database") or os.getenv("SNOWFLAKE_DATABASE")),
        "schema": _text(settings.get("snowflake_schema") or os.getenv("SNOWFLAKE_SCHEMA")),
        "role": _text(settings.get("snowflake_role") or os.getenv("SNOWFLAKE_ROLE")),
        "user": _text(settings.get("snowflake_user") or os.getenv("SNOWFLAKE_USER")),
        "password": _text(settings.get("snowflake_password") or os.getenv("SNOWFLAKE_PASSWORD")),
        "private_key": _text(settings.get("snowflake_private_key") or os.getenv("SNOWFLAKE_PRIVATE_KEY")),
        "private_key_passphrase": _text(os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")),
        "table_allowlist": _validate_allowlist(allowlist),
    }



def snowflake_missing_config(config):
    missing = []
    for field in ("account", "warehouse", "database", "schema", "user"):
        if not _text(config.get(field)):
            missing.append(f"snowflake_{field}")
    if not _text(config.get("password")) and not _text(config.get("private_key")):
        missing.append("snowflake_password_or_private_key")
    if not config.get("table_allowlist"):
        missing.append("snowflake_table_allowlist")
    return missing



def _validate_table_allowed(table_name, allowlist):
    normalized = _normalize_table_name(table_name)
    if normalized in set(allowlist or []):
        return True
    return False



def _serialize_cell(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    return value



def _load_private_key_der(private_key_text, passphrase=""):
    from cryptography.hazmat.primitives import serialization

    private_key_bytes = private_key_text.encode("utf-8")
    password_bytes = passphrase.encode("utf-8") if passphrase else None
    loaded_key = serialization.load_pem_private_key(private_key_bytes, password=password_bytes)
    return loaded_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )



def _build_select_query(table, columns, date_column=None, date_from=None, date_to=None, filters=None, order_by=None, limit=200):
    table_name = _text(table)
    if not _is_valid_table_name(table_name):
        raise ValueError("table must be a valid SQL identifier path (schema.table)")

    requested_columns = columns if isinstance(columns, list) and columns else ["*"]
    if requested_columns == ["*"]:
        select_clause = "*"
    else:
        validated = []
        for item in requested_columns:
            column = _text(item)
            if not _is_valid_identifier(column):
                raise ValueError(f"Invalid column name '{column}'")
            validated.append(column)
        select_clause = ", ".join(validated)

    where_clauses = []
    params = []

    if date_column:
        date_col = _text(date_column)
        if not _is_valid_identifier(date_col):
            raise ValueError("date_column must be a valid identifier")
        if date_from:
            where_clauses.append(f"{date_col} >= %s")
            params.append(_text(date_from))
        if date_to:
            where_clauses.append(f"{date_col} <= %s")
            params.append(_text(date_to))

    for flt in (filters if isinstance(filters, list) else []):
        if not isinstance(flt, dict):
            continue
        column = _text(flt.get("column"))
        operator = _text(flt.get("operator") or "=").lower()
        value = flt.get("value")
        if not _is_valid_identifier(column):
            raise ValueError(f"Invalid filter column '{column}'")
        if operator not in ALLOWED_FILTER_OPS:
            raise ValueError(f"Unsupported filter operator '{operator}'")

        if operator == "in":
            items = value if isinstance(value, list) else []
            if not items:
                continue
            placeholders = ", ".join(["%s"] * len(items))
            where_clauses.append(f"{column} IN ({placeholders})")
            params.extend(items)
        elif operator == "like":
            where_clauses.append(f"{column} ILIKE %s")
            params.append(value)
        else:
            where_clauses.append(f"{column} {operator} %s")
            params.append(value)

    query = f"SELECT {select_clause} FROM {table_name}"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    if order_by:
        order_column = _text(order_by)
        if not _is_valid_identifier(order_column):
            raise ValueError("order_by must be a valid identifier")
        query += f" ORDER BY {order_column}"

    safe_limit = max(1, min(int(limit or 200), 1000))
    query += f" LIMIT {safe_limit}"
    return query, params, safe_limit


def build_query_from_intent(table, columns, query_intent, limit=50):
    """
    Build safe run_allowlisted_query kwargs from a natural-language intent.
    """
    intent = _text(query_intent).lower()
    requested_columns = columns if isinstance(columns, list) and columns else None
    order_by = None

    if any(token in intent for token in ("top", "highest", "largest", "cost", "driver")):
        numeric_candidates = [
            _text(col) for col in (requested_columns or [])
            if any(mark in _text(col).upper() for mark in ("PRICE", "COST", "AMOUNT", "QTY", "VALUE"))
        ]
        if numeric_candidates:
            order_by = numeric_candidates[0]

    return {
        "table": table,
        "columns": requested_columns,
        "order_by": order_by,
        "limit": max(1, min(int(limit or 50), 200)),
    }



def _connect_snowflake(config):
    try:
        import snowflake.connector
    except Exception as exc:
        raise RuntimeError(
            "snowflake-connector-python is not installed in this environment. "
            "Install it in backend requirements to enable Snowflake queries."
        ) from exc

    kwargs = {
        "account": config["account"],
        "user": config["user"],
        "warehouse": config["warehouse"],
        "database": config["database"],
        "schema": config["schema"],
    }
    if _text(config.get("role")):
        kwargs["role"] = config.get("role")

    if _text(config.get("password")):
        kwargs["password"] = config.get("password")
    elif _text(config.get("private_key")):
        kwargs["private_key"] = _load_private_key_der(
            config.get("private_key"),
            passphrase=_text(config.get("private_key_passphrase")),
        )
    else:
        raise RuntimeError("Snowflake password or private key is required.")

    return snowflake.connector.connect(**kwargs)



def test_snowflake_connection(user_id):
    """
    Attempt a lightweight connection test.
    Returns (success: bool, error_message: str).
    """
    try:
        config = snowflake_runtime_config(user_id)
        conn = _connect_snowflake(config)
        try:
            cur = conn.cursor()
            cur.execute("SELECT CURRENT_ACCOUNT()")
            cur.fetchone()
            cur.close()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return True, ""
    except Exception as exc:
        return False, str(exc)


def run_allowlisted_query(user_id, table, *, columns=None, date_column=None, date_from=None, date_to=None, filters=None, order_by=None, limit=200):
    config = snowflake_runtime_config(user_id)
    missing = snowflake_missing_config(config)
    if missing:
        raise RuntimeError(f"Snowflake connector configuration incomplete: {', '.join(missing)}")

    table_name = _normalize_table_name(table)
    if not _validate_table_allowed(table_name, config.get("table_allowlist")):
        raise PermissionError(
            f"Table '{table}' is not in the Snowflake allowlist. "
            f"Allowed tables: {', '.join(config.get('table_allowlist') or [])}"
        )

    query, params, safe_limit = _build_select_query(
        table=table,
        columns=columns,
        date_column=date_column,
        date_from=date_from,
        date_to=date_to,
        filters=filters,
        order_by=order_by,
        limit=limit,
    )

    conn = _connect_snowflake(config)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        headers = [desc[0] for desc in (cursor.description or [])]
        raw_rows = cursor.fetchall()

        rows = []
        for row in raw_rows:
            if not isinstance(row, (list, tuple)):
                continue
            payload = {}
            for index, value in enumerate(row):
                key = headers[index] if index < len(headers) else f"column_{index}"
                payload[key] = _serialize_cell(value)
            rows.append(payload)

        summary = {
            "table": table_name,
            "returned_rows": len(rows),
            "limit": safe_limit,
            "date_from": _text(date_from) or None,
            "date_to": _text(date_to) or None,
            "used_columns": headers,
        }
        return {
            "query": query,
            "params": params,
            "rows": rows,
            "summary": summary,
        }
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass



def extract_kpi_metrics(user_id, table, metric_columns, *, date_column=None, date_from=None, date_to=None):
    data = run_allowlisted_query(
        user_id,
        table,
        columns=metric_columns,
        date_column=date_column,
        date_from=date_from,
        date_to=date_to,
        limit=500,
    )
    rows = data.get("rows") if isinstance(data.get("rows"), list) else []

    metrics = []
    for column in metric_columns or []:
        key = _text(column)
        if not key:
            continue
        values = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        if not values:
            continue
        metrics.append({
            "metric": key,
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
        })

    return {
        "table": data.get("summary", {}).get("table"),
        "metric_count": len(metrics),
        "metrics": metrics,
    }


__all__ = [
    "build_query_from_intent",
    "extract_kpi_metrics",
    "run_allowlisted_query",
    "snowflake_missing_config",
    "snowflake_runtime_config",
    "test_snowflake_connection",
]
