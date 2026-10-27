# GPU price monitor
Zero-dependency script that watches https://thelanternworks.com/api/v1/gpu-prices.json and reports new/changed/removed rates. Run from cron or a GitHub Action (`schedule:`). MIT.

```bash
python monitor.py --gpu H100
```
