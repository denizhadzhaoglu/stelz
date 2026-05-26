FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

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
COPY expand_subculture.py tools/stelz_brand_watch/
COPY tiktok_harvest.py tools/stelz_brand_watch/
COPY detect_pending.py tools/stelz_brand_watch/
COPY process_scan_queue.py tools/stelz_brand_watch/
COPY _brand_refs.py tools/stelz_brand_watch/
COPY _observability.py tools/stelz_brand_watch/
COPY alert_tier1_hits.py tools/stelz_brand_watch/
COPY backfill_worker.py tools/stelz_brand_watch/
COPY send_invite_emails.py tools/stelz_brand_watch/
COPY creator_graph_expand.py tools/stelz_brand_watch/
COPY budget_alerts.py tools/stelz_brand_watch/
COPY zoom_verify.py tools/stelz_brand_watch/
COPY stories_harvest.py tools/stelz_brand_watch/
COPY link_creator_identities.py tools/stelz_brand_watch/
COPY run_prompt_experiment.py tools/stelz_brand_watch/
COPY hashtag_learning.py tools/stelz_brand_watch/
COPY discovery_health.py tools/stelz_brand_watch/
COPY full_stelz_harvest.py tools/stelz_brand_watch/
COPY tiktok_profile_scan.py tools/stelz_brand_watch/
COPY system_health_check.py tools/stelz_brand_watch/

# 17_verify_with_pro.py is referenced by absolute path from the queue
# processor; symlink the canonical filename to the copy we shipped.
RUN ln -s /pa-root/tools/stelz_brand_watch/pro_verify.py /pa-root/tools/stelz_brand_watch/17_verify_with_pro.py
RUN ln -s /pa-root/tools/stelz_brand_watch/daily_scan.py /pa-root/tools/stelz_brand_watch/18_daily_scan.py
RUN ln -s /pa-root/tools/stelz_brand_watch/auto_add.py /pa-root/tools/stelz_brand_watch/19_auto_add.py
RUN ln -s /pa-root/tools/stelz_brand_watch/tiktok_harvest.py /pa-root/tools/stelz_brand_watch/15_tiktok_harvest.py
RUN ln -s /pa-root/tools/stelz_brand_watch/expand_subculture.py /pa-root/tools/stelz_brand_watch/31_expand_subculture.py
RUN ln -s /pa-root/tools/stelz_brand_watch/detect_pending.py /pa-root/tools/stelz_brand_watch/33_detect_pending.py
RUN ln -s /pa-root/tools/stelz_brand_watch/alert_tier1_hits.py /pa-root/tools/stelz_brand_watch/37_alert_tier1_hits.py
RUN ln -s /pa-root/tools/stelz_brand_watch/backfill_worker.py /pa-root/tools/stelz_brand_watch/38_backfill_worker.py
RUN ln -s /pa-root/tools/stelz_brand_watch/send_invite_emails.py /pa-root/tools/stelz_brand_watch/39_send_invite_emails.py
RUN ln -s /pa-root/tools/stelz_brand_watch/creator_graph_expand.py /pa-root/tools/stelz_brand_watch/41_creator_graph_expand.py
RUN ln -s /pa-root/tools/stelz_brand_watch/zoom_verify.py /pa-root/tools/stelz_brand_watch/42_zoom_verify.py
RUN ln -s /pa-root/tools/stelz_brand_watch/budget_alerts.py /pa-root/tools/stelz_brand_watch/43_budget_alerts.py
RUN ln -s /pa-root/tools/stelz_brand_watch/stories_harvest.py /pa-root/tools/stelz_brand_watch/44_stories_harvest.py
RUN ln -s /pa-root/tools/stelz_brand_watch/link_creator_identities.py /pa-root/tools/stelz_brand_watch/45_link_creator_identities.py
RUN ln -s /pa-root/tools/stelz_brand_watch/run_prompt_experiment.py /pa-root/tools/stelz_brand_watch/46_run_prompt_experiment.py
RUN ln -s /pa-root/tools/stelz_brand_watch/hashtag_learning.py /pa-root/tools/stelz_brand_watch/47_hashtag_learning.py
RUN ln -s /pa-root/tools/stelz_brand_watch/perplexity_scout.py /pa-root/tools/stelz_brand_watch/22_perplexity_scout.py
RUN ln -s /pa-root/tools/stelz_brand_watch/full_stelz_harvest.py /pa-root/tools/stelz_brand_watch/12_full_stelz_harvest.py
RUN ln -s /pa-root/tools/stelz_brand_watch/tiktok_profile_scan.py /pa-root/tools/stelz_brand_watch/48_tiktok_profile_scan.py
RUN ln -s /pa-root/tools/stelz_brand_watch/system_health_check.py /pa-root/tools/stelz_brand_watch/50_system_health_check.py

COPY reference-images/ projects/stelz-brand-watch/reference-images/

# Always-on worker: poll scan_requests + subculture_expansions queues forever.
# Railway restartPolicyType=ON_FAILURE will auto-restart on crashes.
CMD ["python", "-u", "tools/stelz_brand_watch/process_scan_queue.py", "--loop"]
