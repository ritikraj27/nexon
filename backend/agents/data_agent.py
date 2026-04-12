# backend/agents/data_agent.py
# ============================================================
# NEXON Data Processing & Analysis Agent
# Handles CSV/Excel/JSON processing, report generation,
# statistical analysis, and chart creation.
# ============================================================

import os
import json
from typing import Dict, List, Optional
from datetime import datetime
from backend.config import DOCUMENTS_DIR
from backend.llm_engine import nexon_llm


class DataAgent:
    """
    Data processing and analysis agent for NEXON.

    Capabilities:
    - Load and summarize CSV, Excel, JSON datasets.
    - Clean data: remove duplicates, fix formats, fill nulls.
    - Transform: pivot, merge, filter, sort.
    - Statistical analysis: mean, median, std, correlations.
    - Generate reports (PDF/HTML/Excel).
    - Create charts using matplotlib.
    - Detect anomalies and trends.
    """

    async def handle(self, intent: str, params: Dict, session_id: str) -> Dict:
        """Route data intents to the appropriate handler."""
        handlers = {
            "process_data"  : self.process_dataset,
            "analyze_data"  : self.analyze_dataset,
            "generate_report": self.generate_report,
            "clean_data"    : self.clean_data,
        }
        handler = handlers.get(intent, self._unknown)
        return await handler(params, session_id)

    # ──────────────────────────────────────────
    # Load Dataset
    # ──────────────────────────────────────────

    def _load_data(self, file_path: str):
        """
        Load a dataset from CSV, Excel, or JSON file.

        Args:
            file_path : Path to the data file.
        Returns:
            pandas DataFrame or None on failure.
        """
        try:
            import pandas as pd
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".csv":
                return pd.read_csv(file_path)
            elif ext in (".xlsx", ".xls"):
                return pd.read_excel(file_path)
            elif ext == ".json":
                return pd.read_json(file_path)
            elif ext == ".tsv":
                return pd.read_csv(file_path, sep="\t")
        except Exception:
            return None

    # ──────────────────────────────────────────
    # Process / Summarize Dataset
    # ──────────────────────────────────────────

    async def process_dataset(self, params: Dict, session_id: str) -> Dict:
        """
        Load a dataset and return a comprehensive summary.

        Args:
            params: {
                file_path (str): Path to data file.
                content   (str): Raw CSV/JSON string (alternative to file_path).
                question  (str): Natural language question about the data.
            }
        """
        try:
            import pandas as pd

            file_path = params.get("file_path", "")
            content   = params.get("content", "")
            question  = params.get("question", "Summarize this dataset")

            # Load from file or raw content
            if file_path and os.path.exists(file_path):
                df = self._load_data(file_path)
            elif content:
                import io
                df = pd.read_csv(io.StringIO(content))
            else:
                return {
                    "success": False,
                    "message": "Please provide a file path or CSV content to analyze.",
                    "action" : {}
                }

            if df is None:
                return {"success": False, "message": "Could not load the dataset.", "action": {}}

            # Basic stats
            shape      = df.shape
            columns    = list(df.columns)
            dtypes     = {col: str(dt) for col, dt in df.dtypes.items()}
            nulls      = df.isnull().sum().to_dict()
            duplicates = int(df.duplicated().sum())

            # Numeric summary
            numeric_cols = df.select_dtypes(include="number").columns.tolist()
            num_summary  = {}
            if numeric_cols:
                desc = df[numeric_cols].describe()
                for col in numeric_cols[:5]:  # Limit to 5 cols
                    num_summary[col] = {
                        "min"  : round(float(desc.loc["min",  col]), 3),
                        "max"  : round(float(desc.loc["max",  col]), 3),
                        "mean" : round(float(desc.loc["mean", col]), 3),
                        "std"  : round(float(desc.loc["std",  col]), 3),
                    }

            # Categorical summary
            cat_cols   = df.select_dtypes(include="object").columns.tolist()
            cat_summary = {}
            for col in cat_cols[:3]:
                vc = df[col].value_counts().head(5)
                cat_summary[col] = dict(zip(vc.index.astype(str), vc.values.tolist()))

            # Build summary text for LLM
            summary_data = {
                "rows"       : shape[0],
                "columns"    : shape[1],
                "column_names": columns,
                "null_counts": nulls,
                "duplicates" : duplicates,
                "numeric"    : num_summary,
                "categorical": cat_summary,
            }

            # LLM insight generation
            llm_prompt = (
                f"Analyze this dataset summary and answer: '{question}'\n\n"
                f"Dataset info:\n{json.dumps(summary_data, indent=2)}\n\n"
                f"Provide key insights, patterns, and recommendations in 3-5 bullet points."
            )
            insights = await nexon_llm.generate_response(llm_prompt, language="en")

            # Format response
            null_str = "\n".join(
                f"  • {k}: {v} nulls" for k, v in nulls.items() if v > 0
            ) or "  None"

            num_str = "\n".join(
                f"  • **{col}**: min={s['min']}, max={s['max']}, mean={s['mean']:.2f}"
                for col, s in num_summary.items()
            ) or "  No numeric columns"

            message = (
                f"📊 **Dataset Analysis**\n\n"
                f"**Shape:** {shape[0]:,} rows × {shape[1]} columns\n"
                f"**Columns:** {', '.join(columns[:8])}{'...' if len(columns) > 8 else ''}\n"
                f"**Duplicates:** {duplicates}\n\n"
                f"**Missing Values:**\n{null_str}\n\n"
                f"**Numeric Columns:**\n{num_str}\n\n"
                f"**AI Insights:**\n{insights}"
            )

            return {
                "success": True,
                "message": message,
                "action" : {
                    "type"   : "data_processed",
                    "details": summary_data
                }
            }

        except ImportError:
            return {
                "success": False,
                "message": "pandas not installed. Run: pip install pandas",
                "action" : {}
            }
        except Exception as e:
            return {"success": False, "message": f"❌ Data processing failed: {str(e)}", "action": {}}

    # ──────────────────────────────────────────
    # Statistical Analysis
    # ──────────────────────────────────────────

    async def analyze_dataset(self, params: Dict, session_id: str) -> Dict:
        """
        Perform deep statistical analysis including correlations and anomaly detection.

        Args:
            params: {
                file_path (str): Path to dataset.
                analysis_type (str): 'correlation'|'anomaly'|'trend'|'full'.
            }
        """
        try:
            import pandas as pd
            import numpy as np

            file_path     = params.get("file_path", "")
            analysis_type = params.get("analysis_type", "full")

            if not file_path or not os.path.exists(file_path):
                return {"success": False, "message": "File not found.", "action": {}}

            df = self._load_data(file_path)
            if df is None:
                return {"success": False, "message": "Could not load dataset.", "action": {}}

            numeric = df.select_dtypes(include="number")
            results = {}

            # Correlation matrix
            if analysis_type in ("correlation", "full") and len(numeric.columns) >= 2:
                corr = numeric.corr().round(3)
                # Find top correlations
                pairs = []
                cols  = list(corr.columns)
                for i in range(len(cols)):
                    for j in range(i+1, len(cols)):
                        val = corr.iloc[i, j]
                        pairs.append((cols[i], cols[j], round(float(val), 3)))
                pairs.sort(key=lambda x: abs(x[2]), reverse=True)
                results["top_correlations"] = pairs[:5]

            # Anomaly detection (Z-score > 3)
            if analysis_type in ("anomaly", "full") and len(numeric.columns) > 0:
                z_scores = np.abs((numeric - numeric.mean()) / numeric.std())
                anomaly_mask = (z_scores > 3).any(axis=1)
                anomaly_count = int(anomaly_mask.sum())
                results["anomalies"] = {
                    "count"     : anomaly_count,
                    "percentage": round(anomaly_count / len(df) * 100, 2)
                }

            # Format
            msg_parts = ["📈 **Statistical Analysis**\n"]

            if "top_correlations" in results:
                corr_str = "\n".join(
                    f"  • {a} ↔ {b}: **{v}**"
                    + (" (strong positive)" if v > 0.7 else
                       " (strong negative)" if v < -0.7 else "")
                    for a, b, v in results["top_correlations"]
                )
                msg_parts.append(f"**Top Correlations:**\n{corr_str}")

            if "anomalies" in results:
                a = results["anomalies"]
                msg_parts.append(
                    f"\n**Anomalies Detected:** {a['count']} rows ({a['percentage']}% of data)"
                )

            return {
                "success": True,
                "message": "\n".join(msg_parts),
                "action" : {"type": "data_analyzed", "details": results}
            }

        except ImportError:
            return {"success": False, "message": "pandas/numpy not installed.", "action": {}}
        except Exception as e:
            return {"success": False, "message": f"❌ Analysis failed: {str(e)}", "action": {}}

    # ──────────────────────────────────────────
    # Report Generation
    # ──────────────────────────────────────────

    async def generate_report(self, params: Dict, session_id: str) -> Dict:
        """
        Generate an HTML data report with charts.

        Args:
            params: {
                file_path   (str): Path to dataset.
                report_name (str): Output filename (without extension).
                chart_type  (str): 'bar'|'line'|'pie' (default 'bar').
            }
        """
        try:
            import pandas as pd
            import matplotlib
            matplotlib.use("Agg")  # Non-interactive backend
            import matplotlib.pyplot as plt

            file_path   = params.get("file_path", "")
            report_name = params.get("report_name", f"report_{datetime.now().strftime('%Y%m%d')}")
            chart_type  = params.get("chart_type", "bar")

            if not file_path or not os.path.exists(file_path):
                return {"success": False, "message": "Dataset file not found.", "action": {}}

            df = self._load_data(file_path)
            if df is None:
                return {"success": False, "message": "Could not load dataset.", "action": {}}

            numeric = df.select_dtypes(include="number")
            if numeric.empty:
                return {"success": False, "message": "No numeric columns to chart.", "action": {}}

            # Generate chart
            chart_path = os.path.join(DOCUMENTS_DIR, f"{report_name}_chart.png")
            plt.figure(figsize=(10, 5))
            col = numeric.columns[0]

            if chart_type == "line":
                plt.plot(numeric[col].values[:50])
                plt.title(f"{col} — Line Chart")
            elif chart_type == "pie" and len(df) <= 10:
                plt.pie(numeric[col].values, labels=df.index, autopct="%1.1f%%")
                plt.title(f"{col} — Pie Chart")
            else:  # bar
                numeric[col].value_counts().head(10).plot(kind="bar")
                plt.title(f"{col} — Bar Chart")
                plt.xticks(rotation=45)

            plt.tight_layout()
            plt.savefig(chart_path, dpi=100, bbox_inches="tight")
            plt.close()

            # Generate HTML report
            html_path = os.path.join(DOCUMENTS_DIR, f"{report_name}.html")
            stats_html = df.describe().to_html(classes="table", border=0)
            sample_html = df.head(10).to_html(classes="table", border=0)

            html = f"""<!DOCTYPE html>
<html><head><title>{report_name}</title>
<style>
  body {{ font-family: Arial; padding: 20px; background: #f5f5f5; }}
  h1 {{ color: #333; }} .table {{ border-collapse: collapse; width: 100%; }}
  .table td, .table th {{ border: 1px solid #ddd; padding: 8px; }}
  img {{ max-width: 100%; margin: 20px 0; }}
</style></head><body>
<h1>📊 NEXON Data Report: {report_name}</h1>
<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
<p><strong>Shape:</strong> {df.shape[0]} rows × {df.shape[1]} columns</p>
<h2>Statistical Summary</h2>{stats_html}
<h2>Chart</h2><img src="{chart_path}" alt="Chart">
<h2>Sample Data (first 10 rows)</h2>{sample_html}
</body></html>"""

            with open(html_path, "w") as f:
                f.write(html)

            return {
                "success": True,
                "message": f"📊 Report generated!\n**HTML:** `{html_path}`\n**Chart:** `{chart_path}`",
                "action" : {
                    "type"   : "report_generated",
                    "details": {"html_path": html_path, "chart_path": chart_path}
                }
            }
        except ImportError as e:
            return {
                "success": False,
                "message": f"Missing library: {e}. Run: pip install pandas matplotlib",
                "action" : {}
            }
        except Exception as e:
            return {"success": False, "message": f"❌ Report generation failed: {str(e)}", "action": {}}

    # ──────────────────────────────────────────
    # Data Cleaning
    # ──────────────────────────────────────────

    async def clean_data(self, params: Dict, session_id: str) -> Dict:
        """
        Clean a dataset: remove duplicates, fix formats, fill nulls.

        Args:
            params: {
                file_path (str): Path to dataset.
                output    (str): Output file path (default: overwrites source).
                operations (list): ['remove_duplicates','fill_nulls','standardize_dates'].
            }
        """
        try:
            import pandas as pd

            file_path  = params.get("file_path", "")
            output     = params.get("output", file_path)
            operations = params.get("operations",
                                    ["remove_duplicates", "fill_nulls", "standardize_dates"])

            if not file_path or not os.path.exists(file_path):
                return {"success": False, "message": "File not found.", "action": {}}

            df        = self._load_data(file_path)
            orig_rows = len(df)
            log       = []

            if "remove_duplicates" in operations:
                before = len(df)
                df.drop_duplicates(inplace=True)
                removed = before - len(df)
                log.append(f"Removed {removed} duplicate rows")

            if "fill_nulls" in operations:
                null_count = df.isnull().sum().sum()
                # Fill numeric with median, categorical with mode
                for col in df.select_dtypes(include="number").columns:
                    df[col].fillna(df[col].median(), inplace=True)
                for col in df.select_dtypes(include="object").columns:
                    mode = df[col].mode()
                    if not mode.empty:
                        df[col].fillna(mode[0], inplace=True)
                log.append(f"Filled {null_count} missing values")

            if "standardize_dates" in operations:
                for col in df.columns:
                    if "date" in col.lower() or "time" in col.lower():
                        try:
                            df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")
                            log.append(f"Standardized dates in column '{col}'")
                        except Exception:
                            pass

            # Save cleaned data
            ext = os.path.splitext(output)[1].lower()
            if ext == ".csv":
                df.to_csv(output, index=False)
            elif ext in (".xlsx", ".xls"):
                df.to_excel(output, index=False)
            else:
                df.to_csv(output, index=False)

            return {
                "success": True,
                "message": (
                    f"✅ Data cleaned!\n"
                    f"Original: {orig_rows} rows → Clean: {len(df)} rows\n"
                    f"Operations:\n" + "\n".join(f"  • {l}" for l in log) +
                    f"\nSaved to: `{output}`"
                ),
                "action" : {"type": "data_cleaned", "details": {"log": log, "output": output}}
            }
        except ImportError:
            return {"success": False, "message": "pandas not installed.", "action": {}}
        except Exception as e:
            return {"success": False, "message": f"❌ Cleaning failed: {str(e)}", "action": {}}

    async def _unknown(self, params: Dict, session_id: str) -> Dict:
        return {"success": False, "message": "Unknown data action.", "action": {}}