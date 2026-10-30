import csv
import io


def export_csv(columns, rows):
    out = io.StringIO()
    writer = csv.writer(out)

    def safe(v):
        if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + v
        return v

    writer.writerow([safe(c) for c in columns])
    writer.writerows([[safe(v) for v in row] for row in rows])
    return "\ufeff" + out.getvalue()
