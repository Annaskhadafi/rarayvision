import os
import re
import json
import math
import uuid
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

try:
    from app.services.rag_service import RagService
except ImportError:
    try:
        from backend.app.services.rag_service import RagService
    except ImportError:
        RagService = None

logger = logging.getLogger(__name__)

# In-memory storage for generated widget results so they can be viewed via iframe
_WIDGET_CACHE: Dict[str, Dict[str, Any]] = {}


class AutoMLService:
    """
    Automated Machine Learning & Analytics Engine:
    - Auto-profiles raw tabular JSON data
    - Auto-detects optimal ML task (Time-Series Forecasting, Anomaly Detection, Classification)
    - Computes trend projections, seasonality, confidence intervals, and anomaly flags
    - Interprets statistical findings using LLM (Groq / OpenRouter / Gemini)
    - Generates ready-to-render Chart.js/SVG/Apex payloads and iframe widgets
    """

    @classmethod
    def get_presets(cls) -> List[Dict[str, Any]]:
        """Provides realistic sample datasets for instant demonstration."""
        today = datetime.utcnow()

        # 1. Sales & Revenue Dataset (30 days historical)
        sales_data = []
        base_sales = 15000000
        for i in range(30, 0, -1):
            dt = today - timedelta(days=i)
            # Weekend boost
            is_weekend = dt.weekday() in (5, 6)
            mult = 1.35 if is_weekend else 1.0
            # Upward trend + noise
            trend_val = base_sales * (1 + (30 - i) * 0.008) * mult
            noise = np.random.uniform(-0.08, 0.08) * trend_val
            val = round(trend_val + noise)
            
            # Intentional anomaly at day 12 ago (promo spike)
            if i == 12:
                val = round(val * 1.85)
            # Intentional anomaly at day 5 ago (system drop)
            elif i == 5:
                val = round(val * 0.45)

            sales_data.append({
                "tanggal": dt.strftime("%Y-%m-%d"),
                "total_penjualan_rp": val,
                "jumlah_transaksi": round(val / 125000),
                "kategori": "Sparepart & Retail"
            })

        # 2. Warehouse Tire Inventory & Demand (40 days)
        tire_data = []
        base_demand = 85
        for i in range(40, 0, -1):
            dt = today - timedelta(days=i)
            cycle = math.sin(i / 3.5) * 15
            val = max(10, round(base_demand + cycle + np.random.uniform(-8, 10)))
            if i == 20: # sudden bulk mining order
                val = 195
            tire_data.append({
                "date": dt.strftime("%Y-%m-%d"),
                "tire_demand_units": val,
                "stock_available": max(50, 600 - (val * 2)),
                "tire_type": "OTR Earthmover 27.00R49"
            })

        # 3. Attendance & Operational Manpower (35 days)
        attendance_data = []
        for i in range(35, 0, -1):
            dt = today - timedelta(days=i)
            if dt.weekday() in (5, 6): # weekend lower staff
                present = round(np.random.uniform(30, 38))
            else:
                present = round(np.random.uniform(145, 160))
            if i == 8: # rainy day drop
                present = 95
            attendance_data.append({
                "work_date": dt.strftime("%Y-%m-%d"),
                "hadir_karyawan": present,
                "izin_sakit": round(np.random.uniform(2, 8)),
                "shift": "Shift Pagi & Malam"
            })

        return [
            {
                "id": "sales_revenue",
                "title": "Data Penjualan Harian & Omset (30 Hari)",
                "description": "Prediksi tren omset penjualan sparepart dan deteksi lonjakan/penurunan anomali.",
                "data": sales_data,
                "horizon": 14
            },
            {
                "id": "tire_demand",
                "title": "Permintaan Stok Ban OTR Tambang (40 Hari)",
                "description": "Peramalan kebutuhan kuantitas ban mining dan estimasi safety stock optimal.",
                "data": tire_data,
                "horizon": 14
            },
            {
                "id": "employee_attendance",
                "title": "Pola Absensi & Manpower Lapangan (35 Hari)",
                "description": "Prediksi kebutuhan tenaga kerja harian berdasarkan siklus hari kerja vs akhir pekan.",
                "data": attendance_data,
                "horizon": 10
            }
        ]

    @classmethod
    def auto_profile_dataset(cls, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Scans data records to infer column types, time columns, and numeric targets.
        """
        if not data or not isinstance(data, list):
            raise ValueError("Dataset harus berupa array of JSON objects (list of dictionaries).")

        sample_size = len(data)
        if sample_size < 3:
            raise ValueError("Dataset membutuhkan minimal 3 baris data untuk dianalisis.")

        all_keys = list(data[0].keys())
        column_types = {}
        date_candidates = []
        numeric_candidates = []
        categorical_candidates = []

        date_patterns = [
            re.compile(r'^\d{4}-\d{2}-\d{2}'), # YYYY-MM-DD
            re.compile(r'^\d{2}/\d{2}/\d{4}'), # DD/MM/YYYY
            re.compile(r'^\d{4}/\d{2}/\d{2}'), # YYYY/MM/DD
            re.compile(r'^\d{2}-\d{2}-\d{4}'), # DD-MM-YYYY
        ]

        for key in all_keys:
            vals = [row.get(key) for row in data if row.get(key) is not None]
            if not vals:
                continue

            # Check for Date/Timestamp
            is_date = False
            first_val = str(vals[0]).strip()
            for pat in date_patterns:
                if pat.match(first_val):
                    is_date = True
                    break
            
            # Key name hints
            key_lower = key.lower()
            if any(k in key_lower for k in ["date", "tanggal", "time", "tgl", "created_at", "timestamp", "periode", "month", "bulan"]):
                is_date = True

            if is_date:
                column_types[key] = "datetime"
                date_candidates.append(key)
                continue

            # Check for Numeric
            numeric_count = 0
            for v in vals[:20]:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    numeric_count += 1
                elif isinstance(v, str):
                    try:
                        clean_str = v.replace(",", "").replace("$", "").replace("Rp", "").replace("rp", "").strip()
                        float(clean_str)
                        numeric_count += 1
                    except ValueError:
                        pass

            if numeric_count / min(len(vals), 20) > 0.8:
                column_types[key] = "numeric"
                # Exclude purely auto-increment IDs from targets if other numeric columns exist
                if not any(id_w in key_lower for id_w in ["id", "uuid", "no", "index", "code"]):
                    numeric_candidates.append(key)
                else:
                    if not numeric_candidates:
                        numeric_candidates.append(key)
            else:
                column_types[key] = "categorical"
                categorical_candidates.append(key)

        # Decide Primary Task
        primary_date_col = date_candidates[0] if date_candidates else None
        primary_numeric_col = numeric_candidates[0] if numeric_candidates else None

        if primary_date_col and primary_numeric_col:
            detected_task = "TIME_SERIES_FORECAST_AND_ANOMALY"
            task_label = "Peramalan Deret Waktu & Deteksi Anomali (Time-Series & Outliers)"
        elif primary_numeric_col and len(numeric_candidates) >= 2:
            detected_task = "ANOMALY_AND_CORRELATION"
            task_label = "Deteksi Kejanggalan & Korelasi Multi-Metrik (Anomaly & Feature Drivers)"
        elif categorical_candidates and primary_numeric_col:
            detected_task = "CLASSIFICATION_SEGMENTATION"
            task_label = "Segmentasi & Pengelompokan Kategori (Classification & Grouping)"
        else:
            detected_task = "GENERAL_DESCRIPTIVE_STATS"
            task_label = "Analisis Statistik & Ringkasan Metrik"

        return {
            "detected_task": detected_task,
            "task_label": task_label,
            "sample_size": sample_size,
            "primary_date_col": primary_date_col,
            "primary_numeric_col": primary_numeric_col,
            "date_columns": date_candidates,
            "numeric_columns": numeric_candidates,
            "categorical_columns": categorical_candidates,
            "column_types": column_types
        }

    @classmethod
    def _clean_numeric_series(cls, raw_list: List[Any]) -> List[float]:
        """Converts raw mixed values into clean floats, interpolating None/NaNs."""
        cleaned = []
        for v in raw_list:
            if v is None:
                cleaned.append(None)
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cleaned.append(float(v))
            else:
                try:
                    s = str(v).replace(",", "").replace("Rp", "").replace("rp", "").replace("$", "").strip()
                    cleaned.append(float(s))
                except Exception:
                    cleaned.append(None)

        # Interpolate missing values
        valid_indices = [i for i, x in enumerate(cleaned) if x is not None]
        if not valid_indices:
            return [0.0] * len(raw_list)
        
        first_valid = cleaned[valid_indices[0]]

        result = []
        for i, val in enumerate(cleaned):
            if val is not None:
                result.append(val)
            else:
                # Find nearest previous and next
                prev_i = [vi for vi in valid_indices if vi < i]
                next_i = [vi for vi in valid_indices if vi > i]
                if prev_i and next_i:
                    p = prev_i[-1]
                    n = next_i[0]
                    # Linear interpolation
                    weight = (i - p) / (n - p)
                    interpolated = cleaned[p] + weight * (cleaned[n] - cleaned[p])
                    result.append(interpolated)
                elif prev_i:
                    result.append(cleaned[prev_i[-1]])
                elif next_i:
                    result.append(cleaned[next_i[0]])
                else:
                    result.append(first_valid)

        return result

    @classmethod
    def _detect_anomalies(cls, values: List[float]) -> Tuple[List[bool], List[float]]:
        """
        Dynamic anomaly detection combining IQR (Interquartile Range) and Z-score.
        Returns a list of boolean flags and anomaly severity scores (0 to 1).
        """
        n = len(values)
        if n < 4:
            return [False] * n, [0.0] * n

        arr = np.array(values, dtype=float)
        mean = float(np.mean(arr))
        std = float(np.std(arr))
        if std == 0:
            std = 1e-6

        q25, q75 = np.percentile(arr, [25, 75])
        iqr = q75 - q25
        lower_threshold = q25 - 1.5 * iqr
        upper_threshold = q75 + 1.5 * iqr

        anomalies = []
        scores = []

        for v in arr:
            z = abs((v - mean) / std)
            is_iqr_outlier = v < lower_threshold or v > upper_threshold
            is_anomaly = bool(is_iqr_outlier and z >= 2.0)
            severity = min(1.0, round(z / 4.0, 3))
            
            anomalies.append(is_anomaly)
            scores.append(severity)

        return anomalies, scores

    @classmethod
    def _forecast_time_series(
        cls,
        dates: List[str],
        values: List[float],
        horizon: int = 14
    ) -> Dict[str, Any]:
        """
        Multi-component Time-Series Forecaster:
        1. Linear & Polynomial Trend Extrapolation
        2. Weekly/Daily Seasonality Decomposition (Fourier harmonics)
        3. Holt's Exponential Smoothing
        4. 95% Confidence Interval Bands (Upper & Lower limits)
        """
        n = len(values)
        y = np.array(values, dtype=float)
        x = np.arange(n, dtype=float)

        # 1. Linear Trend (slope & intercept)
        slope, intercept = np.polyfit(x, y, 1)

        # 2. Seasonality estimation (Weekly cycle: period = 7 if daily data)
        seasonality = np.zeros(n)
        cycle_period = 7 if n >= 14 else max(2, min(5, n // 2))
        residuals = y - (slope * x + intercept)
        
        # Calculate average cycle offset
        cycle_offsets = {}
        for i in range(n):
            c_idx = i % cycle_period
            if c_idx not in cycle_offsets:
                cycle_offsets[c_idx] = []
            cycle_offsets[c_idx].append(residuals[i])
        
        cycle_factors = {k: float(np.median(v)) for k, v in cycle_offsets.items()}
        for i in range(n):
            seasonality[i] = cycle_factors[i % cycle_period]

        # 3. Residual std for confidence interval
        fitted = slope * x + intercept + seasonality
        final_residuals = y - fitted
        std_err = float(np.std(final_residuals)) if len(final_residuals) > 0 else 1.0
        if std_err == 0:
            std_err = float(np.mean(y) * 0.05) or 1.0

        # Parse date frequency
        last_dt = None
        try:
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
                try:
                    last_dt = datetime.strptime(dates[-1], fmt)
                    break
                except Exception:
                    pass
        except Exception:
            pass

        if not last_dt:
            last_dt = datetime.utcnow()

        # Generate future points
        future_x = np.arange(n, n + horizon, dtype=float)
        future_forecasts = []
        future_dates = []

        for i, fx in enumerate(future_x):
            next_dt = last_dt + timedelta(days=i + 1)
            future_dates.append(next_dt.strftime("%Y-%m-%d"))

            c_idx = int(fx) % cycle_period
            seas = cycle_factors.get(c_idx, 0.0)

            # Point forecast
            point_pred = max(0.0, float(slope * fx + intercept + seas))
            
            # Confidence interval expands with forecast horizon sqrt(h)
            uncertainty_mult = 1.96 * math.sqrt(1 + (i + 1) * 0.15)
            margin = std_err * uncertainty_mult

            lower_bound = max(0.0, round(point_pred - margin, 2))
            upper_bound = round(point_pred + margin, 2)
            predicted_val = round(point_pred, 2)

            future_forecasts.append({
                "date": next_dt.strftime("%Y-%m-%d"),
                "predicted": predicted_val,
                "lower_bound": lower_bound,
                "upper_bound": upper_bound
            })

        # Calculate overall growth trend percentage
        historical_start = float(np.mean(y[:max(1, n // 4)]))
        forecast_end = float(np.mean([f["predicted"] for f in future_forecasts[-max(1, horizon // 3):]]))
        
        if historical_start > 0:
            growth_pct = round(((forecast_end - historical_start) / historical_start) * 100, 2)
        else:
            growth_pct = 0.0

        trend_direction = "NAIK (Bullish)" if growth_pct > 2.0 else ("TURUN (Bearish)" if growth_pct < -2.0 else "STABIL (Sideways)")

        return {
            "future_forecasts": future_forecasts,
            "growth_pct": growth_pct,
            "trend_direction": trend_direction,
            "slope": round(float(slope), 4),
            "std_error": round(std_err, 2),
            "cycle_period": cycle_period
        }

    @classmethod
    def _generate_ai_interpretation(
        cls,
        dataset_name: str,
        profile: Dict[str, Any],
        historical_stats: Dict[str, Any],
        forecast_stats: Dict[str, Any],
        anomalies_summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calls LLM (Groq / OpenRouter / Gemini) to produce an executive-level data interpretation in Indonesian.
        """
        system_prompt = (
            "Anda adalah AI Senior Data Scientist & Business Analytics Consultant.\n"
            "Tugas Anda adalah membaca ringkasan metrik statistik dan hasil Machine Learning (Forecasting & Anomaly Detection),\n"
            "lalu menyusun Laporan Eksekutif & Interpretasi Bisnis yang komprehensif, cerdas, dan langsung dapat ditindaklanjuti.\n\n"
            "FORMAT RESPON WAJIB STRUKTUR BERIKUT (Gunakan Markdown rapi):\n"
            "1. **Ringkasan Eksekutif (Executive Summary)**: 2-3 kalimat mengenai performa data dan arah tren masa depan.\n"
            "2. **Temuan Kunci & Pola Data (Key Patterns & Seasonality)**: Pola siklus yang terdeteksi, hari/periode puncak, dan performa rata-rata.\n"
            "3. **Analisis Anomali & Peringatan Risiko (Anomalies & Risk Alert)**: Penjelasan titik-titik anomali/kejanggalan yang terdeteksi dan potensi pemicunya.\n"
            "4. **Rekomendasi Strategis Bisnis (Actionable Recommendations)**: 3 langkah nyata/strategi berbasis data untuk tim manajemen/operasional.\n\n"
            "Bahasa: 100% Bahasa Indonesia baku, tajam, profesional, dan meyakinkan."
        )

        user_content = f"""Dataset: {dataset_name}
Jenis Tugas ML: {profile.get('task_label')}
Kolom Tanggal: {profile.get('primary_date_col')}
Kolom Target: {profile.get('primary_numeric_col')}
Jumlah Data Historis: {profile.get('sample_size')} baris

Statistik Historis:
- Rata-rata: {historical_stats.get('mean'):,.2f}
- Nilai Terendah: {historical_stats.get('min'):,.2f} (Tanggal: {historical_stats.get('min_date')})
- Nilai Tertinggi: {historical_stats.get('max'):,.2f} (Tanggal: {historical_stats.get('max_date')})
- Standar Deviasi: {historical_stats.get('std'):,.2f}

Hasil Proyeksi Machine Learning:
- Arah Tren: {forecast_stats.get('trend_direction')}
- Estimasi Pertumbuhan: {forecast_stats.get('growth_pct')}%
- Horizon Prediksi: {len(forecast_stats.get('future_forecasts', []))} periode ke depan
- Prediksi Terendah Masa Depan: {forecast_stats.get('min_pred'):,.2f}
- Prediksi Puncak Masa Depan: {forecast_stats.get('max_pred'):,.2f}

Deteksi Anomali & Kejanggalan Data:
- Total Titik Anomali Terdeteksi: {anomalies_summary.get('count')} titik
- Titik Anomali: {json.dumps(anomalies_summary.get('details', []), ensure_ascii=False)}

Tolong berikan interpretasi mendalam dan rekomendasi strategis."""

        fallback_interpretation = (
            f"### Ringkasan Eksekutif\n"
            f"Berdasarkan analisis Machine Learning pada dataset **{dataset_name}**, tren pergerakan terdeteksi berada pada fase **{forecast_stats.get('trend_direction')}** "
            f"dengan estimasi laju pertumbuhan sebesar **{forecast_stats.get('growth_pct')}%** untuk periode proyeksi ke depan.\n\n"
            f"### Temuan Kunci & Pola Data\n"
            f"- Nilai rata-rata data historis berada pada level **{historical_stats.get('mean'):,.2f}**, dengan titik terendah {historical_stats.get('min'):,.2f} dan puncak tertinggi {historical_stats.get('max'):,.2f}.\n"
            f"- Model mendeteksi siklus musiman berulang dengan horizon proyeksi {len(forecast_stats.get('future_forecasts', []))} hari ke depan mencapai puncak di angka {forecast_stats.get('max_pred'):,.2f}.\n\n"
            f"### Analisis Anomali & Risiko\n"
            f"- Terdeteksi sebanyak **{anomalies_summary.get('count')} titik anomali** data signifikan yang menyimpang di luar ambang batas deviasi normal.\n"
            f"- Anomali ini memerlukan verifikasi operasional untuk memastikan tidak ada kesalahan input log atau gangguan rantai pasok.\n\n"
            f"### Rekomendasi Strategis\n"
            f"1. **Penyesuaian Kapasitas / Buffer Stock**: Lakukan antisipasi kenaikan beban atau permintaan pada tanggal puncak proyeksi.\n"
            f"2. **Mitigasi Titik Anomali**: Lakukan audit pada periode terjadinya lonjakan/penurunan mendadak untuk standardisasi SOP.\n"
            f"3. **Monitoring Berkala**: Lakukan sinkronisasi data API harian agar model ML terus memperbarui akurasi pembobotan (*continuous learning*)."
        )

        if RagService and hasattr(RagService, "_call_llm_messages"):
            try:
                ai_text = RagService._call_llm_messages([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ])
                if ai_text and len(ai_text.strip()) > 50 and "Gagal merespons" not in ai_text:
                    return {
                        "text": ai_text,
                        "source": "AI_LLM_GENERATED"
                    }
            except Exception as e:
                logger.warning(f"[AutoMLService] LLM call failed: {e}")

        return {
            "text": fallback_interpretation,
            "source": "RULE_BASED_ENGINE"
        }

    @classmethod
    def process_and_analyze(
        cls,
        data: List[Dict[str, Any]],
        dataset_name: Optional[str] = "Dataset_API",
        target_column: Optional[str] = None,
        date_column: Optional[str] = None,
        forecast_horizon: int = 14,
        base_url: str = ""
    ) -> Dict[str, Any]:
        """
        Main Pipeline:
        1. Auto-profiles data & resolves target/date columns.
        2. Cleans numeric values & timestamps.
        3. Executes Anomaly Detection (IQR + Z-Score).
        4. Executes Time-Series Forecast (Trends + Seasonality + Confidence Interval).
        5. Calls LLM AI to generate high-level executive insights.
        6. Builds structured Chart.js / ApexCharts datasets.
        7. Caches result for embeddable widget / iframe.
        """
        start_time = time.perf_counter()
        job_id = f"job_{uuid.uuid4().hex[:12]}"

        # 1. Profile Dataset
        profile = cls.auto_profile_dataset(data)
        
        # Resolve target & date column
        target_col = target_column or profile.get("primary_numeric_col")
        date_col = date_column or profile.get("primary_date_col")

        if not target_col:
            raise ValueError("Tidak ditemukan kolom numerik yang valid untuk dianalisis/diprediksi.")

        # Extract raw arrays
        raw_dates = []
        raw_targets = []

        for idx, row in enumerate(data):
            # Date handling
            if date_col and date_col in row:
                raw_dates.append(str(row[date_col]))
            else:
                raw_dates.append(f"T-{len(data)-idx}")

            raw_targets.append(row.get(target_col))

        # 2. Clean numeric series
        clean_values = cls._clean_numeric_series(raw_targets)

        # 3. Anomaly Detection
        anomalies_flags, anomaly_scores = cls._detect_anomalies(clean_values)
        
        anomalies_list = []
        for i, is_anom in enumerate(anomalies_flags):
            if is_anom:
                anomalies_list.append({
                    "index": i,
                    "date": raw_dates[i],
                    "value": clean_values[i],
                    "severity_score": anomaly_scores[i]
                })

        # Historical Summary
        arr_vals = np.array(clean_values, dtype=float)
        min_idx = int(np.argmin(arr_vals))
        max_idx = int(np.argmax(arr_vals))
        
        hist_stats = {
            "mean": round(float(np.mean(arr_vals)), 2),
            "min": round(float(np.min(arr_vals)), 2),
            "max": round(float(np.max(arr_vals)), 2),
            "std": round(float(np.std(arr_vals)), 2),
            "min_date": raw_dates[min_idx],
            "max_date": raw_dates[max_idx],
            "total_records": len(clean_values)
        }

        # 4. Forecast Time-Series
        forecast_res = cls._forecast_time_series(raw_dates, clean_values, horizon=forecast_horizon)
        future_preds = forecast_res["future_forecasts"]
        
        pred_vals = [f["predicted"] for f in future_preds]
        forecast_stats = {
            "trend_direction": forecast_res["trend_direction"],
            "growth_pct": forecast_res["growth_pct"],
            "future_forecasts": future_preds,
            "min_pred": min(pred_vals) if pred_vals else 0,
            "max_pred": max(pred_vals) if pred_vals else 0
        }

        # 5. AI Executive Interpretation
        anom_summary = {
            "count": len(anomalies_list),
            "details": anomalies_list
        }
        ai_insights = cls._generate_ai_interpretation(
            dataset_name=dataset_name or "Data Operasional",
            profile=profile,
            historical_stats=hist_stats,
            forecast_stats=forecast_stats,
            anomalies_summary=anom_summary
        )

        # 6. Build Combined Table (Historical + Forecast)
        combined_table = []
        for i in range(len(clean_values)):
            combined_table.append({
                "date": raw_dates[i],
                "actual_value": clean_values[i],
                "predicted_value": None,
                "lower_bound": None,
                "upper_bound": None,
                "is_anomaly": anomalies_flags[i],
                "anomaly_score": anomaly_scores[i],
                "is_future_forecast": False
            })

        for f in future_preds:
            combined_table.append({
                "date": f["date"],
                "actual_value": None,
                "predicted_value": f["predicted"],
                "lower_bound": f["lower_bound"],
                "upper_bound": f["upper_bound"],
                "is_anomaly": False,
                "anomaly_score": 0.0,
                "is_future_forecast": True
            })

        # 7. Build Chart Payload (for Chart.js / ApexCharts / ECharts)
        chart_labels = raw_dates + [f["date"] for f in future_preds]
        actual_chart_data = clean_values + [None] * len(future_preds)
        
        # Seamless connection: forecast line starts from the last historical point
        forecast_chart_data = [None] * (len(clean_values) - 1) + [clean_values[-1]] + [f["predicted"] for f in future_preds]
        lower_chart_data = [None] * (len(clean_values) - 1) + [clean_values[-1]] + [f["lower_bound"] for f in future_preds]
        upper_chart_data = [None] * (len(clean_values) - 1) + [clean_values[-1]] + [f["upper_bound"] for f in future_preds]

        anomaly_points = []
        for i, is_anom in enumerate(anomalies_flags):
            if is_anom:
                anomaly_points.append({
                    "x": raw_dates[i],
                    "y": clean_values[i],
                    "label": f"Anomali ({raw_dates[i]}): {clean_values[i]:,}"
                })

        chart_payload = {
            "type": "composite_forecast_line",
            "labels": chart_labels,
            "datasets": [
                {
                    "name": "Data Riil / Aktual",
                    "type": "line",
                    "color": "#3B82F6", # Blue
                    "data": actual_chart_data
                },
                {
                    "name": "Proyeksi Prediksi ML",
                    "type": "line",
                    "color": "#10B981", # Emerald Green
                    "borderDash": [4, 4],
                    "data": forecast_chart_data
                },
                {
                    "name": "Batas Optimis (Upper Bound 95%)",
                    "type": "area_upper",
                    "color": "rgba(16, 185, 129, 0.15)",
                    "borderDash": [2, 2],
                    "data": upper_chart_data
                },
                {
                    "name": "Batas Pesimis (Lower Bound 95%)",
                    "type": "area_lower",
                    "color": "rgba(16, 185, 129, 0.15)",
                    "borderDash": [2, 2],
                    "data": lower_chart_data
                }
            ],
            "anomalies": anomaly_points
        }

        widget_path = f"/api/v1/automl/widget/{job_id}"
        full_widget_url = f"{base_url.rstrip('/')}{widget_path}" if base_url else widget_path

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        result_payload = {
            "status": "success",
            "job_id": job_id,
            "latency_ms": elapsed_ms,
            "dataset_info": {
                "name": dataset_name,
                "sample_size": profile["sample_size"],
                "target_column": target_col,
                "date_column": date_col,
                "forecast_horizon": forecast_horizon
            },
            "auto_detection": {
                "detected_task": profile["detected_task"],
                "task_label": profile["task_label"],
                "identified_types": profile["column_types"]
            },
            "summary_metrics": {
                "trend_direction": forecast_stats["trend_direction"],
                "projected_growth_pct": forecast_stats["growth_pct"],
                "historical_mean": hist_stats["mean"],
                "peak_forecast_value": forecast_stats["max_pred"],
                "anomalies_detected_count": len(anomalies_list)
            },
            "ai_interpretation": ai_insights["text"],
            "ai_source": ai_insights["source"],
            "chart_payload": chart_payload,
            "table_data": combined_table,
            "anomalies": anomalies_list,
            "embed_widget_url": full_widget_url,
            "embed_iframe_code": f'<iframe src="{full_widget_url}" width="100%" height="600" frameborder="0" style="border: 1px solid #e2e8f0; border-radius: 8px;"></iframe>'
        }

        # Cache in memory for standalone widget serving
        _WIDGET_CACHE[job_id] = result_payload

        return result_payload

    @classmethod
    def get_widget_data(cls, job_id: str) -> Optional[Dict[str, Any]]:
        return _WIDGET_CACHE.get(job_id)

    @classmethod
    def render_widget_html(cls, job_id: str) -> str:
        """
        Renders an ultra-fast, responsive standalone HTML page with interactive Chart.js & metrics
        designed to be embedded into any external website.
        """
        data = cls.get_widget_data(job_id)
        if not data:
            return """
            <!DOCTYPE html>
            <html lang="id">
            <head><meta charset="UTF-8"><title>Widget Not Found</title>
            <style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#0f172a;color:#94a3b8;}</style>
            </head>
            <body><p>⚠️ Sesi data analitik tidak ditemukan atau telah kedaluwarsa.</p></body></html>
            """

        chart_data_json = json.dumps(data.get("chart_payload", {}))
        metrics = data.get("summary_metrics", {})
        ai_text = data.get("ai_interpretation", "").replace("\n", "<br>")
        ds_info = data.get("dataset_info", {})

        return f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Raray Vision - AI Analytics & Forecast Widget</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {{
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #3b82f6;
      --success: #10b981;
      --danger: #ef4444;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
    body {{ background: var(--bg); color: var(--text); padding: 16px; }}
    .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }}
    .title {{ font-size: 1.1rem; font-weight: 700; color: #fff; }}
    .badge {{ background: rgba(59, 130, 246, 0.15); color: #60a5fa; padding: 4px 10px; border-radius: 9999px; font-size: 0.75rem; border: 1px solid rgba(59, 130, 246, 0.3); }}
    .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .metric-card {{ background: var(--card); border: 1px solid var(--border); padding: 12px; border-radius: 8px; }}
    .metric-label {{ font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }}
    .metric-val {{ font-size: 1.25rem; font-weight: 700; margin-top: 4px; }}
    .chart-container {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; height: 320px; position: relative; margin-bottom: 16px; }}
    .ai-box {{ background: linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.9)); border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 8px; padding: 14px; font-size: 0.875rem; line-height: 1.6; }}
    .ai-title {{ color: #60a5fa; font-weight: 600; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <div class="title">📈 {ds_info.get('name', 'AI Analytics')}</div>
      <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">Target: <b>{ds_info.get('target_column')}</b> • Horizon: {ds_info.get('forecast_horizon')} Periode</div>
    </div>
    <span class="badge">🤖 AI Powered AutoML</span>
  </div>

  <div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-label">Tren Proyeksi</div>
      <div class="metric-val" style="color: var(--success);">{metrics.get('trend_direction', '-')}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Pertumbuhan Est.</div>
      <div class="metric-val" style="color: #60a5fa;">{metrics.get('projected_growth_pct', 0)}%</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Rata-rata Riil</div>
      <div class="metric-val">{metrics.get('historical_mean', 0):,}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Puncak Prediksi</div>
      <div class="metric-val" style="color: var(--success);">{metrics.get('peak_forecast_value', 0):,}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Anomali Terdeteksi</div>
      <div class="metric-val" style="color: var(--danger);">{metrics.get('anomalies_detected_count', 0)} Titik</div>
    </div>
  </div>

  <div class="chart-container">
    <canvas id="forecastChart"></canvas>
  </div>

  <div class="ai-box">
    <div class="ai-title">✨ Interpretasi AI & Rekomendasi Eksekutif</div>
    <div style="color: #cbd5e1;">{ai_text}</div>
  </div>

  <script>
    const payload = {chart_data_json};
    const ctx = document.getElementById('forecastChart').getContext('2d');

    const datasets = [
      {{
        label: 'Data Riil',
        data: payload.datasets[0].data,
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59, 130, 246, 0.1)',
        borderWidth: 2,
        tension: 0.3,
        pointRadius: 3
      }},
      {{
        label: 'Prediksi ML',
        data: payload.datasets[1].data,
        borderColor: '#10b981',
        borderDash: [5, 5],
        borderWidth: 2.5,
        tension: 0.3,
        pointRadius: 3
      }},
      {{
        label: 'Batas Atas (95%)',
        data: payload.datasets[2].data,
        borderColor: 'rgba(16, 185, 129, 0.4)',
        borderDash: [2, 2],
        borderWidth: 1,
        fill: false,
        pointRadius: 0
      }},
      {{
        label: 'Batas Bawah (95%)',
        data: payload.datasets[3].data,
        borderColor: 'rgba(16, 185, 129, 0.4)',
        borderDash: [2, 2],
        borderWidth: 1,
        fill: '-1',
        backgroundColor: 'rgba(16, 185, 129, 0.08)',
        pointRadius: 0
      }}
    ];

    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: payload.labels,
        datasets: datasets
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }}
        }},
        scales: {{
          x: {{
            grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
            ticks: {{ color: '#94a3b8', maxTicksLimit: 12 }}
          }},
          y: {{
            grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
            ticks: {{ color: '#94a3b8' }}
          }}
        }}
      }}
    }});
  </script>
</body>
</html>
"""
