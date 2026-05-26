FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Script computes PA_ROOT as parent.parent.parent of itself.
# Mirror that path: /pa-root/tools/stelz_brand_watch/daily_scan.py
# -> PA_ROOT becomes /pa-root, and reference-images sits under /pa-root/projects/stelz-brand-watch/
WORKDIR /pa-root

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p tools/stelz_brand_watch projects/stelz-brand-watch
COPY daily_scan.py tools/stelz_brand_watch/
COPY auto_add.py tools/stelz_brand_watch/
COPY auto_prune.py tools/stelz_brand_watch/
COPY ai_score_creators.py tools/stelz_brand_watch/
COPY perplexity_scout.py tools/stelz_brand_watch/
COPY pro_verify.py tools/stelz_brand_watch/
COPY train_from_moderator.py tools/stelz_brand_watch/
COPY daily_email_report.py tools/stelz_brand_watch/
COPY credit_lifecycle.py tools/stelz_brand_watch/
COPY daily_pipeline.sh .
RUN chmod +x daily_pipeline.sh
COPY reference-images/ projects/stelz-brand-watch/reference-images/

CMD ["./daily_pipeline.sh"]
