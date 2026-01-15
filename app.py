#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 后端服务
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from std_crawler import StdCrawler

app = FastAPI(
    title="标准信息爬虫 API",
    description="全国标准信息公共服务平台爬虫接口",
    version="1.0.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 存储爬取任务状态
tasks_status = {}

# 数据存储目录
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


class SearchRequest(BaseModel):
    """搜索请求参数"""
    keyword: str
    max_pages: int = 3
    std_type: str = "全部"
    std_status: str = "全部"


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str
    status: str
    message: str


@app.get("/")
async def root():
    """API根路径"""
    return {
        "name": "标准信息爬虫 API",
        "version": "1.0.0",
        "endpoints": {
            "search": "/api/search",
            "status": "/api/status/{task_id}",
            "results": "/api/results/{task_id}",
            "download": "/api/download/{task_id}"
        }
    }


@app.post("/api/search", response_model=TaskResponse)
async def start_search(request: SearchRequest, background_tasks: BackgroundTasks):
    """
    启动爬取任务
    """
    # 生成任务ID
    task_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 初始化任务状态
    tasks_status[task_id] = {
        "status": "running",
        "progress": 0,
        "message": "正在启动爬虫...",
        "keyword": request.keyword,
        "results": [],
        "total": 0,
        "created_at": datetime.now().isoformat()
    }

    # 后台执行爬取任务
    background_tasks.add_task(
        run_crawler,
        task_id,
        request.keyword,
        request.max_pages,
        request.std_type,
        request.std_status
    )

    return TaskResponse(
        task_id=task_id,
        status="running",
        message=f"爬取任务已启动，关键词: {request.keyword}"
    )


async def run_crawler(task_id: str, keyword: str, max_pages: int,
                      std_type: str, std_status: str):
    """
    执行爬取任务
    """
    crawler = StdCrawler(headless=True, delay=1.5)

    try:
        tasks_status[task_id]["message"] = "正在启动浏览器..."
        await crawler.start()

        tasks_status[task_id]["message"] = f"正在搜索: {keyword}"

        # 执行搜索
        results = await crawler.search(
            keyword=keyword,
            max_pages=max_pages,
            std_type=std_type,
            std_status=std_status
        )

        # 更新任务状态
        tasks_status[task_id]["status"] = "completed"
        tasks_status[task_id]["message"] = f"爬取完成，共获取 {len(results)} 条记录"
        tasks_status[task_id]["results"] = results
        tasks_status[task_id]["total"] = len(results)
        tasks_status[task_id]["progress"] = 100

        # 保存结果到文件
        result_file = DATA_DIR / f"results_{task_id}.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        tasks_status[task_id]["file"] = str(result_file)

    except Exception as e:
        tasks_status[task_id]["status"] = "failed"
        tasks_status[task_id]["message"] = f"爬取失败: {str(e)}"

    finally:
        await crawler.close()


@app.get("/api/status/{task_id}")
async def get_task_status(task_id: str):
    """
    获取任务状态
    """
    if task_id not in tasks_status:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = tasks_status[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "total": task.get("total", 0),
        "keyword": task.get("keyword", "")
    }


@app.get("/api/results/{task_id}")
async def get_task_results(task_id: str, page: int = 1, page_size: int = 20):
    """
    获取爬取结果
    """
    if task_id not in tasks_status:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = tasks_status[task_id]
    results = task.get("results", [])

    # 分页
    total = len(results)
    start = (page - 1) * page_size
    end = start + page_size
    paginated_results = results[start:end]

    return {
        "task_id": task_id,
        "status": task["status"],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "results": paginated_results
    }


@app.get("/api/download/{task_id}")
async def download_results(task_id: str, format: str = "json"):
    """
    下载爬取结果
    """
    if task_id not in tasks_status:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = tasks_status[task_id]
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    results = task.get("results", [])

    if format == "json":
        filename = f"standards_{task_id}.json"
        filepath = DATA_DIR / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        return FileResponse(
            filepath,
            media_type="application/json",
            filename=filename
        )

    elif format == "csv":
        import csv
        filename = f"standards_{task_id}.csv"
        filepath = DATA_DIR / filename

        if results:
            fieldnames = list(results[0].keys())
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(results)

        return FileResponse(
            filepath,
            media_type="text/csv",
            filename=filename
        )

    else:
        raise HTTPException(status_code=400, detail="不支持的格式")


@app.get("/api/history")
async def get_history():
    """
    获取历史任务列表
    """
    history = []
    for task_id, task in tasks_status.items():
        history.append({
            "task_id": task_id,
            "keyword": task.get("keyword", ""),
            "status": task["status"],
            "total": task.get("total", 0),
            "created_at": task.get("created_at", "")
        })

    # 按时间倒序排列
    history.sort(key=lambda x: x["created_at"], reverse=True)
    return {"history": history}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
