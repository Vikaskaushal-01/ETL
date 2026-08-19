import os
import sys
import xml.etree.ElementTree as ET

sys.path.append(r"c:\Users\User\Documents\ETL-A")
from backend.utils.flowchart_generator import generate_svg_fallback

stages = {
    "intake": {"status": "completed", "output": {"rows": 100, "columns": 5, "estimated_quality": 95}},
    "transformation": {"status": "completed", "output": {"quality_after": 98}},
    "storage": {"status": "completed", "output": {"format_selected": "CSV", "rows_loaded": 100}},
    "report": {"status": "completed", "output": {"rca_alerts_count": 0}},
    "pbi": {"status": "completed"}
}

svg_content = generate_svg_fallback("test_batch", stages, "customers_dirty.xml")

try:
    ET.fromstring(svg_content)
    print("Direct SVG XML Parsing Succeeded!")
except Exception as e:
    print("XML Parsing Failed:")
    print(e)
