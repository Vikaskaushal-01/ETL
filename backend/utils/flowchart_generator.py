import logging

logger = logging.getLogger("flowchart_generator")

def generate_svg_fallback(batch_id: str, stages: dict, filename: str) -> str:
    """
    Generates a premium, responsive SVG flowchart representing the data flow pipeline stages
    and metadata in real time without external executable dependencies.
    """
    # Define colors matching the UI theme
    colors = {
        "completed": "#10b981", # emerald green
        "processing": "#f59e0b", # warning orange
        "failed": "#ef4444", # rose red
        "waiting": "#475569" # slate gray
    }
    
    # Get current status of each stage
    intake_status = stages.get("intake", {}).get("status", "waiting")
    trans_status = stages.get("transformation", {}).get("status", "waiting")
    storage_status = stages.get("storage", {}).get("status", "waiting")
    report_status = stages.get("report", {}).get("status", "waiting")
    pbi_status = stages.get("pbi", {}).get("status", "waiting")
    
    # Get data attributes
    intake_out = stages.get("intake", {}).get("output", {})
    trans_out = stages.get("transformation", {}).get("output", {})
    storage_out = stages.get("storage", {}).get("output", {})
    report_out = stages.get("report", {}).get("output", {})
    
    intake_rows = intake_out.get("rows", "-")
    intake_cols = intake_out.get("columns", "-")
    intake_qual = intake_out.get("estimated_quality", "-")
    
    trans_qual = trans_out.get("quality_after", "-")
    
    storage_fmt = storage_out.get("format_selected", "-")
    storage_loaded = storage_out.get("rows_loaded", "-")
    
    rca_alerts = report_out.get("rca_alerts_count", 0)
    
    # Node Status Colors
    c_intake = colors.get(intake_status, colors["waiting"])
    c_trans = colors.get(trans_status, colors["waiting"])
    c_storage = colors.get(storage_status, colors["waiting"])
    c_report = colors.get(report_status, colors["waiting"])
    c_pbi = colors.get(pbi_status, colors["waiting"])
    
    # Check if we have active elements
    raw_status = "completed" if intake_status != "waiting" else "waiting"
    c_raw = colors[raw_status]

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 185" style="width: 100%; height: auto; background: transparent; font-family: 'Outfit', -apple-system, sans-serif;">
  <defs>
    <filter id="glow-raw" x="-10%" y="-10%" width="120%" height="120%">
      <feGaussianBlur stdDeviation="4" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
    <linearGradient id="grad-line" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#00f0ff" stop-opacity="0.8"/>
      <stop offset="100%" stop-color="#14b8a6" stop-opacity="0.8"/>
    </linearGradient>
  </defs>

  <style>
    .node-rect {{ rx: 8px; ry: 8px; fill: rgba(15, 23, 42, 0.75); stroke-width: 1.5; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5)); }}
    .node-header {{ font-size: 11px; font-weight: 800; fill: #94a3b8; letter-spacing: 0.5px; }}
    .node-title {{ font-size: 12px; font-weight: 600; fill: #ffffff; }}
    .node-meta {{ font-size: 9.5px; fill: #cbd5e1; }}
    .node-status {{ font-size: 9px; font-weight: 700; text-transform: uppercase; }}
    .conn-line {{ stroke: rgba(255,255,255,0.08); stroke-width: 1.5; stroke-dasharray: 4 3; fill: none; }}
    .conn-line-active {{ stroke: url(#grad-line); stroke-width: 2.5; stroke-dasharray: 1000; stroke-dashoffset: 0; fill: none; animation: dash 10s linear infinite; }}
    .badge-rect {{ rx: 3px; ry: 3px; }}
  </style>

  <!-- Connection Edges (Lines) -->
  <line x1="140" y1="80" x2="190" y2="80" class="{'conn-line-active' if intake_status != 'waiting' else 'conn-line'}" />
  <line x1="330" y1="80" x2="370" y2="80" class="{'conn-line-active' if trans_status != 'waiting' else 'conn-line'}" />
  <line x1="510" y1="80" x2="550" y2="80" class="{'conn-line-active' if storage_status != 'waiting' else 'conn-line'}" />
  <line x1="690" y1="80" x2="730" y2="80" class="{'conn-line-active' if report_status != 'waiting' else 'conn-line'}" />
  <line x1="870" y1="80" x2="910" y2="80" class="{'conn-line-active' if pbi_status != 'waiting' else 'conn-line'}" />

  <!-- Node 0: Raw Ingestion Input -->
  <g transform="translate(10, 30)">
    <rect width="130" height="100" class="node-rect" stroke="{c_raw}" />
    <text x="12" y="24" class="node-header">STAGE 0</text>
    <text x="12" y="44" class="node-title">Raw Dataset</text>
    <text x="12" y="65" class="node-meta" style="fill:#a855f7; font-weight:600;">{filename[:18] + '..' if len(filename) > 18 else filename}</text>
    <text x="12" y="80" class="node-meta">Format: {filename.split('.')[-1].upper() if '.' in filename else 'Unknown'}</text>
    <rect x="90" y="10" width="30" height="15" class="badge-rect" fill="{c_raw}" opacity="0.2"/>
    <text x="105" y="21" text-anchor="middle" class="node-status" fill="{c_raw}">{raw_status[:4]}</text>
  </g>

  <!-- Node 1: Intake Agent -->
  <g transform="translate(190, 30)">
    <rect width="140" height="100" class="node-rect" stroke="{c_intake}" />
    <text x="12" y="24" class="node-header">STAGE 1</text>
    <text x="12" y="44" class="node-title">Iris AI Intake</text>
    <text x="12" y="65" class="node-meta">Rows: {intake_rows} | Cols: {intake_cols}</text>
    <text x="12" y="80" class="node-meta">Est. Quality: {intake_qual}%</text>
    <rect x="95" y="10" width="35" height="15" class="badge-rect" fill="{c_intake}" opacity="0.2"/>
    <text x="112" y="21" text-anchor="middle" class="node-status" fill="{c_intake}">{intake_status[:4]}</text>
  </g>

  <!-- Node 2: Transformation Agent -->
  <g transform="translate(370, 30)">
    <rect width="140" height="100" class="node-rect" stroke="{c_trans}" />
    <text x="12" y="24" class="node-header">STAGE 2</text>
    <text x="12" y="44" class="node-title">Data Cleanser</text>
    <text x="12" y="65" class="node-meta">Standardized Header</text>
    <text x="12" y="80" class="node-meta">Clean Quality: {trans_qual}%</text>
    <rect x="95" y="10" width="35" height="15" class="badge-rect" fill="{c_trans}" opacity="0.2"/>
    <text x="112" y="21" text-anchor="middle" class="node-status" fill="{c_trans}">{trans_status[:4]}</text>
  </g>

  <!-- Node 3: Storage Agent -->
  <g transform="translate(550, 30)">
    <rect width="140" height="100" class="node-rect" stroke="{c_storage}" />
    <text x="12" y="24" class="node-header">STAGE 3</text>
    <text x="12" y="44" class="node-title">SQL Staging</text>
    <text x="12" y="65" class="node-meta">Format: {storage_fmt}</text>
    <text x="12" y="80" class="node-meta">Rows Loaded: {storage_loaded}</text>
    <rect x="95" y="10" width="35" height="15" class="badge-rect" fill="{c_storage}" opacity="0.2"/>
    <text x="112" y="21" text-anchor="middle" class="node-status" fill="{c_storage}">{storage_status[:4]}</text>
  </g>

  <!-- Node 4: Report Agent -->
  <g transform="translate(730, 30)">
    <rect width="140" height="100" class="node-rect" stroke="{c_report}" />
    <text x="12" y="24" class="node-header">STAGE 4</text>
    <text x="12" y="44" class="node-title">Docx &amp; Reports</text>
    <text x="12" y="65" class="node-meta">RCA Alerts: {rca_alerts}</text>
    <text x="12" y="80" class="node-meta">DOCX/PDF Gen</text>
    <rect x="95" y="10" width="35" height="15" class="badge-rect" fill="{c_report}" opacity="0.2"/>
    <text x="112" y="21" text-anchor="middle" class="node-status" fill="{c_report}">{report_status[:4]}</text>
  </g>

  <!-- Node 5: Power BI Sync -->
  <g transform="translate(910, 30)">
    <rect width="140" height="100" class="node-rect" stroke="{c_pbi}" />
    <text x="12" y="24" class="node-header">STAGE 5</text>
    <text x="12" y="44" class="node-title">Power BI Sync</text>
    <text x="12" y="65" class="node-meta">MySQL Staging DB</text>
    <text x="12" y="80" class="node-meta">Gateway: Synced</text>
    <rect x="95" y="10" width="35" height="15" class="badge-rect" fill="{c_pbi}" opacity="0.2"/>
    <text x="112" y="21" text-anchor="middle" class="node-status" fill="{c_pbi}">{pbi_status[:4]}</text>
  </g>
</svg>
"""
    return svg_content

def generate_flowchart_svg(batch_id: str, stages: dict, filename: str) -> str:
    """SVG flowchart of the pipeline stages and their current status."""
    return generate_svg_fallback(batch_id, stages, filename)
