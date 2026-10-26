import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def read_json(request, label):
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except Exception:
        # 不打印异常内容，避免推送地址中的密钥出现在日志里。
        sys.exit(f"{label}失败，请检查服务状态及仓库机密。")


def main():
    config_path = Path(__file__).with_name("config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    token = os.environ.get("TMDB_READ_ACCESS_TOKEN", "").strip()
    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if not token or not sendkey:
        sys.exit("缺少 TMDB_READ_ACCESS_TOKEN 或 SERVERCHAN_SENDKEY。")
    if not sendkey.startswith("SCT"):
        sys.exit("请使用以 SCT 开头的 Server酱 Turbo SendKey。")

    today = datetime.now(ZoneInfo(config["timezone"])).date()
    past_days = int(config["past_days"])
    future_days = int(config["future_days"])
    limit = int(config["max_items_per_section"])
    if past_days < 1 or future_days < 1 or not 1 <= limit <= 10:
        sys.exit("配置中的天数须大于零，每栏数量须在 1 到 10 之间。")

    # 近期含今天，共 past_days 天；未来从明天开始，避免重复。
    periods = [
        (
            "近期已上",
            today - timedelta(days=past_days - 1),
            today,
        ),
        (
            "即将上线",
            today + timedelta(days=1),
            today + timedelta(days=future_days),
        ),
    ]

    kinds = []
    if config.get("include_movies"):
        kinds.append(("movie", "电影", "primary_release_date", "release_date"))
    if config.get("include_tv"):
        kinds.append(("tv", "新剧", "first_air_date", "first_air_date"))
    if not kinds:
        sys.exit("请在配置中至少开启电影或电视剧。")

    sections = [
        f"# MovieRadar · {today}",
        "日期为 TMDB 收录的电影主要上映日期／新剧首次开播日期，"
        "不代表国内平台上线时间。按热度选取，每栏最多 "
        f"{limit} 部；中文资料缺失时显示原名。"
        "窗口内的作品可能连续几天重复出现。",
    ]

    for period_name, start, end in periods:
        for kind, kind_name, filter_field, date_field in kinds:
            params = {
                "language": config["language"],
                "with_origin_country": "|".join(config["origin_countries"]),
                "include_adult": "false",
                "sort_by": "popularity.desc",
                f"{filter_field}.gte": str(start),
                f"{filter_field}.lte": str(end),
                "page": 1,
            }
            url = (
                f"https://api.themoviedb.org/3/discover/{kind}?"
                + urllib.parse.urlencode(params)
            )
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                },
            )
            data = read_json(request, f"获取{period_name}{kind_name}")
            if not isinstance(data.get("results"), list):
                sys.exit("TMDB 返回的数据格式异常，未发送日报。")

            lines = [
                f"## {period_name} · {kind_name}",
                f"{start} 至 {end}",
            ]
            items = data["results"][:limit]
            if not items:
                lines.append("本次未找到符合条件的作品。")

            for item in items:
                title = (
                    item.get("title")
                    or item.get("name")
                    or item.get("original_title")
                    or item.get("original_name")
                    or "暂无名称"
                )
                title = " ".join(title.split())
                date = item.get(date_field) or "日期待定"
                if item.get("vote_count", 0) > 0:
                    rating = f'{item.get("vote_average", 0):.1f}/10'
                else:
                    rating = "暂无评分"
                overview = " ".join(
                    (item.get("overview") or "暂无中文简介。").split()
                )
                if len(overview) > 100:
                    overview = overview[:100] + "…"
                link = (
                    f"https://www.themoviedb.org/{kind}/{item['id']}"
                )
                lines.append(
                    f"### {title}\n"
                    f"日期：{date} ｜ TMDB：{rating}\n\n"
                    f"{overview}\n\n"
                    f"[查看详情]({link})"
                )

            sections.append("\n\n".join(lines))

    sections.append(
        "资料来源：TMDB。本项目使用 TMDB API，"
        "但未经 TMDB 认可或认证。"
    )
    message = "\n\n".join(sections)
    print(message)

    body = urllib.parse.urlencode({
        "title": f"MovieRadar 新片新剧 · {today}",
        "desp": message,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://sctapi.ftqq.com/" + sendkey + ".send",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    result = read_json(request, "微信推送请求；请先查看微信是否已收到消息")
    if result.get("code") != 0:
        sys.exit("推送服务未确认成功，请查看 Server酱推送日志。")
    print("推送服务已接受日报，请查看微信。")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit("程序未完成，请检查 config.json 内容及文件是否完整。")
