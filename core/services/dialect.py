"""T-SQL helpers for report SQL."""


def month_expr(column):
    return f"DATEADD(month, DATEDIFF(month, 0, {column}), 0)"


def limit_clause(count):
    return f"OFFSET 0 ROWS FETCH NEXT {count} ROWS ONLY"
