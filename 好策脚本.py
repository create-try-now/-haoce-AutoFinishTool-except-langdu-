"""
好策（HaoCe）平台自动化脚本
功能：
  - 自动登录、获取书籍列表与任务需求
  - 支持三种运行模式：检测模式（手动查看）、自动模式（真实执行）、校验模式（模拟并展示AI生成内容）
  - 集成 AI 内容生成（兼容 Ollama/OpenAI 协议），可选联网搜索增强
  - 朗读任务因VITS复杂无法自动化，提示用户自行完成
所有可配置项集中在文件开头，修改常量即可适配不同环境和行为。
"""

import os
import re
import json
import uuid
import time
import random
import shutil
import subprocess
from typing import Dict, List, Tuple, Optional
import requests

# ======================== 基础配置（必须自行填写） ========================
USERNAME = "15360639001"      # 替换为您的 openid
PASSWORD = "haoce_112233"     # 替换为您的密码
BASE_URL = "https://appclient.haoce.com"

# ======================== AI 与搜索配置 ========================
AI_ENABLED = True                       # 是否启用 AI 生成内容；若 False 则仅使用内置模板
# AI 接口地址：需兼容 OpenAI Chat Completions 协议，例如 Ollama 的地址通常为 http://localhost:11434/v1/chat/completions
AI_CHAT_URL = "http://localhost:11434/v1/chat/completions"
AI_API_KEY = "ollama"                   # API 密钥（Ollama 可随意填写，OpenAI 需真实 key）
AI_MODEL = "my-gemma4"                  # 模型名称
AI_MAX_TOKENS = 2000                    # 生成内容的最大 token 数
AI_TEMPERATURE = 0.8                    # 温度参数，控制随机性（0 到 2，越高越随机）
AI_TIMEOUT = 30                         # AI 请求超时秒数

# -------- 各任务系统提示词（静态配置，可自由修改以适配不同风格）--------
AI_SYSTEM_PROMPT_DISCUSS = (
    "You are a careful reader participating in an online book discussion. "
    "Base all statements on the actual plot of the book. "
    "Never invent details, locations, or character reactions that contradict the original story. "
    "If you are unsure about a specific detail, speak in general terms about themes instead."
)
AI_SYSTEM_PROMPT_COMMENT = (
    "You are a participant in a book discussion. Reply to the post based strictly on what happens in the book. "
    "Do NOT assume the characters feel typical human emotions unless clearly shown in the text. "
    "If the question involves a specific scene, recall the character's actual reaction rather than what might be expected. "
    "Keep the reply natural and around 20-40 words."
)
AI_SYSTEM_PROMPT_REPORT = (
    "You are a student writing a book report. Use ONLY accurate details from the original text. "
    "Double-check key facts: where the story begins, character backgrounds, and major events. "
    "If you cannot confirm a detail (e.g., a location or a minor character's action), either omit it or describe it in a general way. "
    "Write a well-structured report of at least 250 words with a clear ending."
)
AI_SYSTEM_PROMPT_EXCERPT = (
    "You are a thoughtful reader sharing an insight about a book quote. "
    "Analyze the given quote in the context of the book, and make sure your interpretation is grounded in the actual storyline. "
    "Write a complete analysis of at least 20 words."
)
AI_SYSTEM_PROMPT_SUMMARY = (
    "You are a helpful assistant summarizing a book. Provide a concise summary using only verified plot points. "
    "Do not guess the ending or fabricate relationships. Aim for 50-80 words."
)

# -------- 联网搜索配置（可选，用于生成更丰富的内容）--------
SEARCH_ENABLED = False                  # 是否启用联网搜索
# 搜索 API 地址，需自行搭建或使用第三方服务。{query} 会被自动替换为关键词（已 URL 编码）
SEARCH_URL = "http://localhost:8080/search?q={query}"
SEARCH_API_KEY = ""                     # 搜索 API 的密钥（如需），会自动加在 Authorization 头
SEARCH_TIMEOUT = 10                     # 搜索请求超时秒数
SEARCH_RESULT_COUNT = 3                 # 注入到 AI 提示中的搜索结果数量

# ======================== 公共请求头 ========================
BASE_HEADERS = {
    "Accept": "application/json",
    "X-Display": "json",
    "X-Requested-With": "",
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 12; M2004J7AC Build/SP1A.210812.016; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/99.0.4844.88 "
        "Mobile Safari/537.36 uni-app Html5Plus/1.0 (Immersed/25.09091)"
    ),
    "Origin": BASE_URL,                 # 用于跨域请求
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
}

# ======================== 内容模板（AI 不可用时的后备方案） ========================
TEMPLATES = {
    "discuss_topic": [                  # 讨论帖内容模板，每个帖子至少 20 词
        "I really enjoyed this chapter because the character development is impressive. "
        "The way Mary transforms from a selfish girl to a caring person is truly inspiring. "
        "What are your thoughts on this change?",
        "The author's description of the secret garden makes me think about healing and friendship. "
        "I believe nature can heal our minds. Do you agree with this idea?",
        "I found it interesting that the garden acts as a mirror of the soul. "
        "When Mary starts caring for the garden, she also starts caring for others. "
        "This is a powerful metaphor for personal growth.",
        "This part shows that happiness grows from within. The garden doesn't magically fix everything; "
        "it gives Mary a purpose. Very inspiring lesson for all of us."
    ],
    "report": [                         # 读书报告模板，需 ≥250 词
        "After reading The Secret Garden by Frances Hodgson Burnett, I have gained a profound understanding "
        "of the healing power of nature and positive thinking. The story follows Mary Lennox, a spoiled and "
        "lonely orphan who is sent to live with her uncle in Yorkshire. At first, Mary is disagreeable and "
        "selfish, but she gradually changes after discovering a hidden, locked garden. With the help of Dickon, "
        "a kind boy who can talk to animals, and her sickly cousin Colin, Mary brings the garden back to life. "
        "As the flowers bloom, the children themselves are transformed: Mary becomes healthier and friendlier, "
        "and Colin learns to walk and laugh again.\n\nOne of the main themes of the book is the healing power "
        "of nature. Burnett shows that caring for living things can heal both the body and the heart. The "
        "magical change from a cold, dead garden into a colourful, lively place mirrors the inner changes of "
        "the characters. I found this story deeply moving because it teaches that happiness is not given to us "
        "but grows from our own efforts and from connecting with others and the natural world.\n\nAnother "
        "important theme is the importance of positive thinking. Colin is convinced that he is going to die, "
        "but through Mary's insistence and the magic of the garden, he learns to think positively and becomes "
        "strong. This reminds me of the saying, 'Whether you think you can or you think you can't, you're "
        "right.' Burnett beautifully illustrates that our mindset can shape our reality.\n\nWhat impressed me "
        "most is how the author uses simple, beautiful language to create a sense of hope and renewal. Reading "
        "this book made me want to step outside and appreciate the small miracles of growing things. It is a "
        "gentle reminder that even after the darkest winter, spring will always return. I would recommend this "
        "book to anyone who enjoys classic literature with strong messages about friendship, resilience, and "
        "the wonder of nature. In conclusion, The Secret Garden is a timeless masterpiece that teaches us that "
        "love, friendship, and nature have the power to heal and transform. I highly recommend it to readers "
        "of all ages."
    ],
    "excerpt": [                        # 摘抄见解模板，见解部分需 ≥20 词
        "One beautiful sentence from the book: 'Where you tend a rose, my lad, a thistle cannot grow.' "
        "My understanding: this reflects the importance of focusing on good things. If we fill our minds "
        "with positive thoughts and actions, negative ones cannot take root. This is a powerful lesson for "
        "daily life."
    ],
    "comment": [                        # 回帖模板，需言之有物
        "Great post! I totally agree with your point. Your analysis of Mary's transformation is very insightful. "
        "Thanks for sharing your thoughts!",
        "Well said! I hadn't considered the garden as a symbol of the subconscious mind before. This adds a new "
        "layer to my understanding. Keep up the good work!",
        "Interesting perspective! The way you connected the garden's revival to personal growth is brilliant. "
        "I believe you are absolutely right. Thank you for this post.",
        "Thanks for your insights. This helps me appreciate the book even more. I particularly liked your "
        "observation about Colin's change. Very helpful!"
    ]
}

# ======================== 工具函数 ========================
def random_delay(seconds=2):
    """随机延迟，模拟人类操作"""
    time.sleep(random.uniform(1.5, seconds))

def build_mb_data(wid: str) -> Dict:
    """构造 MB_* 公共参数"""
    return {
        "MB_time": str(int(time.time())),
        "MB_version": "3.4.5",
        "MB_uuid": str(uuid.uuid4()).replace('-', ''),
        "push_cid": "null",
        "push_token": "null",
        "MB_wid": wid
    }

# ======================== AI 内容生成器 ========================
class AIContentGenerator:
    """AI 内容生成器，支持 Ollama / OpenAI 兼容协议，可选联网搜索。"""
    def __init__(self):
        self.chat_url = AI_CHAT_URL
        self.api_key = AI_API_KEY
        self.model = AI_MODEL
        self.max_tokens = AI_MAX_TOKENS
        self.temperature = AI_TEMPERATURE
        self.timeout = AI_TIMEOUT

        self.search_enabled = SEARCH_ENABLED
        self.search_url = SEARCH_URL
        self.search_api_key = SEARCH_API_KEY
        self.search_timeout = SEARCH_TIMEOUT
        self.search_result_count = SEARCH_RESULT_COUNT

    def _call_chat_api(self, messages: List[Dict]) -> Optional[str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }
        try:
            resp = requests.post(self.chat_url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"].strip()
            print("AI 返回格式异常:", data)
            return None
        except Exception as e:
            print(f"AI 调用失败: {e}")
            return None

    def _search(self, query: str) -> str:
        if not self.search_enabled:
            return ""
        try:
            url = self.search_url.format(query=requests.utils.quote(query))
            headers = {}
            if self.search_api_key:
                headers["Authorization"] = f"Bearer {self.search_api_key}"
            resp = requests.get(url, headers=headers, timeout=self.search_timeout)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return ""
            snippets = []
            for i, res in enumerate(results[:self.search_result_count]):
                snippets.append(f"{i+1}. {res.get('title', '')}\n{res.get('snippet', '')}")
            return "Search results:\n" + "\n".join(snippets)
        except Exception as e:
            print(f"搜索失败: {e}")
            return ""

    def _generate_with_context(self, system_prompt: str, user_prompt: str,
                               search_query: str = None) -> Optional[str]:
        context = ""
        if search_query:
            context = self._search(search_query)
        final_user = f"{context}\n\nBased on the above information, {user_prompt}" if context else user_prompt
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": final_user}
        ]
        return self._call_chat_api(messages)

    def generate_discuss_topic(self, book_name: str = "The Secret Garden") -> Optional[str]:
        prompt = (f"Write a short discussion post about the book '{book_name}'. "
                  "Include your thoughts on character development, themes, or personal reflections. "
                  "The post must be at least 20 words and sound natural.")
        return self._generate_with_context(AI_SYSTEM_PROMPT_DISCUSS, prompt,
                                           search_query=f"{book_name} book discussion questions")

    def generate_comment(self, post_snippet: str = "") -> Optional[str]:
        prompt = (f"Reply to the following post snippet: \"{post_snippet}\". "
                  "Provide an insightful, supportive comment related to the book. "
                  "Keep it short (around 20-40 words) and natural.")
        return self._generate_with_context(AI_SYSTEM_PROMPT_COMMENT, prompt)

    def generate_report(self, book_name: str = "The Secret Garden") -> Optional[str]:
        prompt = (f"Write a book report on '{book_name}' by Frances Hodgson Burnett. "
                  "Summarize the plot, discuss main themes (e.g., healing power of nature, positive thinking), "
                  "include personal reflection, and a recommendation. The report must be at least 250 words. "
                  "Use paragraph breaks and formal but engaging language.")
        return self._generate_with_context(AI_SYSTEM_PROMPT_REPORT, prompt,
                                           search_query=f"{book_name} Frances Hodgson Burnett summary analysis")

    def generate_excerpt_insight(self, quote: str = "") -> Optional[str]:
        prompt = (f"Given the quote \"{quote}\" from 'The Secret Garden', "
                  "write a short personal understanding or analysis of the quote. "
                  "Explain its meaning and relevance to the story. The insight must be at least 20 words.")
        return self._generate_with_context(AI_SYSTEM_PROMPT_EXCERPT, prompt)

    def generate_summary(self, book_name: str = "The Secret Garden") -> Optional[str]:
        prompt = (f"Provide a concise summary of the book '{book_name}' in about 50-80 words. "
                  "Focus on the main plot, character growth, and the central message.")
        return self._generate_with_context(AI_SYSTEM_PROMPT_SUMMARY, prompt,
                                           search_query=f"{book_name} plot summary")

# ======================== 好策客户端 ========================
class HaoCeClient:
    """好策平台 API 客户端，封装所有接口与业务流程。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(BASE_HEADERS)
        self.user_id = None
        self.replied_topics = set()
        self._raw_me_data = None
        self.books = []
        self.current_book = None
        self.dry_run = False
        self.ai_generator = AIContentGenerator() if AI_ENABLED else None
        # 用于缓存摘抄候选句子，避免重复拉取
        self._excerpt_cache = {}

    # ------------------------- 登录 -------------------------
    def login(self):
        url = f"{BASE_URL}/app/login/post"
        data = {"openid": USERNAME, "psw": PASSWORD}
        resp = self.session.post(url, data=data)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error") != 0:
            raise Exception(f"登录失败: {result.get('error_des')}")
        print("登录成功:", result["redirect"]["msg"])
        return True

    # ------------------------- 书籍列表与任务 -------------------------
    def fetch_books(self) -> List[Dict]:
        url = f"{BASE_URL}/book/me/cj"
        data = build_mb_data("bookOne")
        data["MB_os"] = json.dumps({"android": True, "version": "12", "isBadAndroid": False, "plus": True})
        resp = self.session.post(url, data=data)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error") != 0:
            raise Exception(f"获取书籍列表失败: {result.get('error_des')}")
        all_books = result["data"].get("books", {})
        info_list = result["data"].get("info", [])
        books = []
        for item in info_list:
            book_id = str(item.get("book_id"))
            book_name = all_books.get(book_id, {}).get("book", f"书籍 {book_id}")
            config = {
                "user_topic": int(all_books.get(book_id, {}).get("user_topic", 2)),
                "user_comment": int(all_books.get(book_id, {}).get("user_comment", 10)),
                "tag_3_config": int(all_books.get(book_id, {}).get("tag_3_config", 10)),
                "tag_5_config": int(all_books.get(book_id, {}).get("tag_5_config", 1)),
                "tag_6_config": int(all_books.get(book_id, {}).get("tag_6_config", 10)),
            }
            books.append({
                "book_id": book_id,
                "name": book_name,
                "config": config,
                "detail": item.get("detail", {})
            })
        books.sort(key=lambda x: int(x["book_id"]))
        self._raw_me_data = result["data"]
        cu = self._raw_me_data.get("_cu")
        if isinstance(cu, dict):
            self.user_id = cu.get("uid")
        self.books = books
        return books

    def parse_task_requirements(self, detail: Dict, config: Dict) -> Dict:
        tasks = {}
        disc = detail.get("0")
        if disc:
            finish = disc.get("finish") == "是"
            if finish:
                need_topic, need_comment = 0, 0
            else:
                done_topic = int(disc.get("count", {}).get("topic", 0))
                done_comment = int(disc.get("count", {}).get("comment", 0))
                total_topic = config.get("user_topic", 2)
                total_comment = config.get("user_comment", 10)
                need_topic = max(0, total_topic - done_topic)
                need_comment = max(0, total_comment - done_comment)
            tasks[0] = {"need_topic": need_topic, "need_comment": need_comment, "finished": finish}
        read = detail.get("3")
        if read:
            finish = read.get("finish") == "是"
            need = 0 if finish else max(0, config.get("tag_3_config", 10) - int(read.get("count", 0)))
            tasks[3] = {"need": need, "finished": finish}
        summary = detail.get("4")
        if summary:
            finish = summary.get("finish") == "是"
            tasks[4] = {"need": 0 if finish else 1, "finished": finish}
        report = detail.get("5")
        if report:
            finish = report.get("finish") == "是"
            need = 0 if finish else max(0, config.get("tag_5_config", 1) - int(report.get("count", 0)))
            tasks[5] = {"need": need, "finished": finish}
        excerpt = detail.get("6")
        if excerpt:
            finish = excerpt.get("finish") == "是"
            need = 0 if finish else max(0, config.get("tag_6_config", 10) - int(excerpt.get("count", 0)))
            tasks[6] = {"need": need, "finished": finish}
        return tasks

    # ------------------------- 发帖 -------------------------
    def add_topic(self, book_id: str, tag_id: int, title: str, content: str,
                  extra_yanwen: str = "") -> Optional[str]:
        if self.dry_run:
            print(f"[校验模式] 将发送发帖请求: book_id={book_id}, tag={tag_id}, title={title}")
            return "dry_run_topic_id"
        url = f"{BASE_URL}/book/topicAdd"
        word_cnt = len(content.split())
        data = {
            "topic": title,
            "topic_info": content,
            "type": "0",
            "attr[stop]": "0",
            "tag_id": str(tag_id),
            "book_id": str(book_id),
            "word_cnt": str(word_cnt),
            "topic_id": "0",
            "yuan_word_cnt": "0",
            "topic_info_yanwen": extra_yanwen,
            "t_id": "undefined",
        }
        mb = build_mb_data(f"app/page/topicNew?book_id={book_id}&tag_id={tag_id}")
        mb["MB_os"] = json.dumps({"android": True, "version": "12", "isBadAndroid": False, "plus": True})
        data.update(mb)
        resp = self.session.post(url, data=data)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error") != 0:
            print(f"发帖失败: {result.get('error_des')}")
            return None
        print(f"发帖成功: {title}")
        return result.get("data", {}).get("topic_id")

    def add_discuss_topic(self, book_id: str, content: str) -> Optional[str]:
        book_name = self.current_book["name"] if self.current_book else "Book"
        title = f"Discussion about {book_name} - {random.randint(100, 999)}"
        return self.add_topic(book_id, 0, title, content)

    # ------------------------- 回帖 -------------------------
    def get_topic_list(self, book_id: str, tag_id: int, page: int = 1) -> Tuple[List[Dict], int]:
        url = f"{BASE_URL}/app/bookOne/topicList/{book_id}?pageno={page}"
        data = {
            "tag_id": str(tag_id),
            "page": str(page),
            "sort": "time",
            "search_name": "",
        }
        mb = build_mb_data("bookOne")
        mb["MB_os"] = json.dumps({"android": True, "version": "12", "isBadAndroid": False, "plus": True})
        data.update(mb)
        resp = self.session.post(url, data=data)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error") != 0:
            raise Exception(f"获取帖子列表失败: {result.get('error_des')}")
        topic_data = result["data"]["topic_list"]
        topics = topic_data["list"]
        page_total = int(topic_data.get("page_total", 1))
        return topics, page_total

    def add_comment(self, book_id: str, topic_id: str, content: str) -> bool:
        if self.dry_run:
            print(f"[校验模式] 将发送回帖请求: topic_id={topic_id}, content={content[:30]}...")
            return True
        if topic_id in self.replied_topics:
            print(f"跳过已回复的帖子 {topic_id}")
            return False
        url = f"{BASE_URL}/book/commentAdd/{book_id}/{topic_id}"
        word_cnt = len(content.split())
        data = {
            "topic_id": topic_id,
            "comment": content,
            "word_cnt": str(word_cnt),
            "reply_id": "0",
            "reply_name": "",
        }
        mb = build_mb_data("topic")
        mb["MB_os"] = json.dumps({"android": True, "version": "12", "isBadAndroid": False, "plus": True})
        data.update(mb)
        resp = self.session.post(url, data=data)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error") != 0:
            print(f"评论失败: {result.get('error_des')}")
            return False
        print(f"评论成功: {content[:30]}...")
        self.replied_topics.add(topic_id)
        return True

    # ------------------------- 朗读（已禁用自动化，提示用户自行完成） -------------------------
    def get_chapter_list(self, book_id: str) -> Tuple[List[Dict], Dict]:
        novel_id = "35"
        url = f"{BASE_URL}/book/novel/listV2?id={novel_id}&book_id={book_id}"
        data = build_mb_data("readerFull")
        data["MB_os"] = json.dumps({"android": True, "version": "12", "isBadAndroid": False, "plus": True})
        resp = self.session.post(url, data=data)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error") != 0:
            raise Exception(f"获取章节列表失败: {result.get('error_des')}")
        chapters = result["data"]["novel"]["chapter"]
        novel_obj = result["data"]["novel"].get("novel", {})
        return chapters, novel_obj

    def get_chapter_content(self, cp_id: str, book_id: str, novel_obj: Dict) -> List[Dict]:
        url = f"{BASE_URL}/book/novel/chapter/{cp_id}"
        data = {}
        for k, v in novel_obj.items():
            if isinstance(v, dict):
                for subk, subv in v.items():
                    data[f"novel[{k}][{subk}]"] = str(subv)
            else:
                data[f"novel[{k}]"] = str(v)
        data["book_id"] = book_id
        mb = build_mb_data("readerFull")
        mb["MB_os"] = json.dumps({"android": True, "version": "12", "isBadAndroid": False, "plus": True})
        data.update(mb)
        resp = self.session.post(url, data=data)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error") != 0:
            raise Exception(f"获取章节内容失败: {result.get('error_des')}")
        return result["data"]["chapter"]["contents"]

    def upload_reading(self, book_id: str, paragraph_text: str, audio_file_path: str,
                       duration_sec: int = 5) -> bool:
        if self.dry_run:
            print(f"[校验模式] 将上传朗读音频: 段落={paragraph_text[:30]}...")
            return True
        url = f"{BASE_URL}/book/topicAdd/tag3"
        filename = f"{int(time.time()*1000)}.amr"
        attr_json = json.dumps({"path": f"_doc/audio/{filename}", "time": duration_sec, "ext": "amr"})
        data = {
            "topic": "", "topic_info": paragraph_text, "type": "0", "attr": attr_json,
            "tag_id": "3", "book_id": str(book_id), "word_cnt": "0",
            "topic_id": "0", "yuan_word_cnt": "0", "topic_info_yanwen": "",
        }
        mb = build_mb_data(f"app/page/topicNew?book_id={book_id}&tag_id=3")
        mb["MB_os"] = json.dumps({"android": True, "version": "12", "isBadAndroid": False, "plus": True})
        data.update(mb)
        with open(audio_file_path, 'rb') as f:
            files = {'file': (filename, f, 'audio/amr')}
            headers = BASE_HEADERS.copy()
            headers.pop("Content-Type", None)
            resp = self.session.post(url, data=data, files=files, headers=headers)
            resp.raise_for_status()
            result = resp.json()
            if result.get("error") == 0:
                print(f"朗读提交成功: {paragraph_text[:30]}...")
                return True
            else:
                print(f"朗读提交失败: {result.get('error_des')}")
                return False

    def generate_silent_amr(self, duration_sec: int = 5, output_path: str = "temp_silent.amr") -> str:
        ffmpeg_exe = shutil.which('ffmpeg')
        if not ffmpeg_exe:
            raise RuntimeError("未找到 ffmpeg，请安装并配置 PATH")
        cmd = [
            ffmpeg_exe, '-f', 'lavfi', '-i', 'anullsrc=r=8000:cl=stereo',
            '-t', str(duration_sec), '-acodec', 'libopencore_amrnb',
            '-ar', '8000', '-ac', '1', '-y', output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return output_path

    def complete_reading(self, book_id: str, need: int, word_requirement: int = 60):
        if need <= 0:
            return
        # ====== 以下朗读自动化代码已注释，请用户自行完成 ======
        # print(f"需要完成朗读 {need} 段，每段不少于 {word_requirement} 词。")
        # chapters, novel_obj = self.get_chapter_list(book_id)
        # candidate_paragraphs = []
        # for chapter in chapters:
        #     cp_id = chapter["cp_id"]
        #     contents = self.get_chapter_content(cp_id, book_id, novel_obj)
        #     for item in contents:
        #         if item.get("type") == "text" and item.get("lg") == "en":
        #             raw_text = re.sub(r'<[^>]+>', '', item.get("text", ""))
        #             if len(raw_text.split()) >= word_requirement:
        #                 candidate_paragraphs.append(raw_text)
        #                 if len(candidate_paragraphs) >= need:
        #                     break
        #     if len(candidate_paragraphs) >= need:
        #         break
        # if len(candidate_paragraphs) < need:
        #     print(f"警告：只找到 {len(candidate_paragraphs)} 个满足条件的段落，需要 {need} 个")
        #     need = len(candidate_paragraphs)
        # if need == 0:
        #     print("没有找到可朗读的段落")
        #     return
        # audio_file = self.generate_silent_amr(5, "temp_reading.amr")
        # for idx, para in enumerate(candidate_paragraphs[:need]):
        #     print(f"朗读第 {idx+1} 段: {para[:60]}...")
        #     if not self.upload_reading(book_id, para, audio_file, 5):
        #         break
        #     random_delay(3)
        # if os.path.exists(audio_file):
        #     os.remove(audio_file)
        print("朗读任务：由于VITS仿真声音调节复杂，无法自动化，请用户自行完成。")

    # ----- 获取摘抄候选句子（缓存） -----
    def _get_excerpt_candidates(self, book_id: str) -> List[str]:
        """从书籍章节中提取适合摘抄的英文句子，带缓存"""
        if book_id in self._excerpt_cache:
            return self._excerpt_cache[book_id]
        candidates = []
        try:
            chapters, novel_obj = self.get_chapter_list(book_id)
            for chapter in chapters:
                contents = self.get_chapter_content(chapter["cp_id"], book_id, novel_obj)
                for item in contents:
                    if item.get("type") == "text" and item.get("lg") == "en":
                        raw = re.sub(r'<[^>]+>', '', item.get("text", ""))
                        sentences = re.split(r'(?<=[.!?])\s+', raw)
                        for sent in sentences:
                            if 10 <= len(sent.split()) <= 80:
                                candidates.append(sent.strip())
        except Exception as e:
            print(f"获取摘抄候选句子失败: {e}")
        self._excerpt_cache[book_id] = candidates
        return candidates

    # ------------------------- 自动执行（单本书） -------------------------
    def run_auto_on_book(self, book: Dict):
        """处理单本书的所有任务，自动模式显示原始输入与AI回复的对应关系"""
        book_id = book["book_id"]
        book_name = book["name"]
        config = book["config"]
        detail = book["detail"]
        ai = self.ai_generator

        print(f"\n========== 开始处理: {book_name} (ID: {book_id}) ==========")

        # ---------- 校验模式 ----------
        if self.dry_run:
            print("[校验模式] 忽略实际完成状态，将所有任务视为未完成并进行模拟生成。")
            tasks = {
                0: {"need_topic": 1, "need_comment": 1},
                5: {"need": 1}, 6: {"need": 1}, 4: {"need": 1}, 3: {"need": 1},
            }

            # 讨论发帖
            print(f"\n>>> 模拟讨论发帖（需要1篇）")
            print(f"[话题] {book_name}")
            content = ai.generate_discuss_topic(book_name) if ai else None
            if not content:
                content = random.choice(TEMPLATES["discuss_topic"])
            print(f"[AI 生成讨论帖内容]\n{content}")
            self.add_discuss_topic(book_id, content)

            # 报告
            print(f"\n>>> 模拟读书报告（需要1篇）")
            print(f"[书名] {book_name}")
            content = ai.generate_report(book_name) if ai else None
            if not content:
                content = TEMPLATES["report"][0]
            print(f"[AI 生成报告内容]\n{content}")
            self.add_topic(book_id, 5, f"Reading Report on {book_name}", content)

            # 摘抄（随机真实原文）
            print(f"\n>>> 模拟摘抄（需要1段）")
            candidates = self._get_excerpt_candidates(book_id)
            quote = random.choice(candidates) if candidates else "The magic of the garden healed them all."
            print(f"[摘抄原文] {quote}")
            insight = ai.generate_excerpt_insight(quote) if ai else None
            if not insight:
                insight = TEMPLATES["excerpt"][0].split("My understanding:")[1].strip()
            print(f"[AI 生成见解]\n{insight}")
            self.add_topic(book_id, 6, f"Excerpt from {book_name}", quote, extra_yanwen=insight)

            # 概要
            print(f"\n>>> 模拟概要（需要1篇）")
            print(f"[书名] {book_name}")
            content = ai.generate_summary(book_name) if ai else None
            if not content:
                content = "This book tells a story of transformation through nature and friendship."
            print(f"[AI 生成概要内容]\n{content}")
            self.add_topic(book_id, 4, f"Summary of {book_name}", content)

            # 回帖
            print(f"\n>>> 模拟回帖（需要1次）")
            snippet = ""
            selected = {"topic_id": "dry_run_1"}
            try:
                topics, _ = self.get_topic_list(book_id, 0, 1)
                if topics:
                    candidates = [t for t in topics if t.get("user_id") != self.user_id]
                    if not candidates:
                        candidates = topics
                    selected = random.choice(candidates)
                    full_text = selected.get("topic_info") or selected.get("topic", "")
                    snippet = full_text[:200].strip()
                    print(f"[原帖 ID={selected.get('topic_id')}] {snippet}{'...' if len(full_text) > 200 else ''}")
            except Exception as e:
                print(f"获取帖子列表失败: {e}")
            if not snippet:
                snippet = "I think the secret garden symbolizes hope."
                print(f"[模拟原帖] {snippet}")
            content = ai.generate_comment(snippet) if ai else None
            if not content:
                content = random.choice(TEMPLATES["comment"])
            print(f"[AI 回复]\n{content}")
            self.add_comment(book_id, selected["topic_id"], content)

            # 朗读（校验模式下也仅提示）
            print(f"\n>>> 模拟朗读（需要1段）")
            print("朗读任务：由于VITS仿真声音调节复杂，无法自动化，请用户自行完成。")

            print(f"\n[校验模式] 书籍 {book_name} 模拟执行完毕。")
            return

        # ========== 正常自动模式 ==========
        max_retries = 3
        for retry in range(max_retries):
            tasks = self.parse_task_requirements(detail, config)
            print("\n当前任务状态：")
            any_incomplete = False
            for tag, req in tasks.items():
                if tag == 0:
                    if req["need_topic"] > 0 or req["need_comment"] > 0:
                        any_incomplete = True
                    print(f"讨论: 发帖还需 {req['need_topic']} 次, 回帖还需 {req['need_comment']} 次")
                elif tag == 5:
                    if req["need"] > 0: any_incomplete = True
                    print(f"报告: 还需 {req['need']} 篇")
                elif tag == 6:
                    if req["need"] > 0: any_incomplete = True
                    print(f"摘抄: 还需 {req['need']} 段")
                elif tag == 4:
                    if req["need"] > 0: any_incomplete = True
                    print(f"概要: 还需 {req['need']} 篇")
                elif tag == 3:
                    if req["need"] > 0: any_incomplete = True
                    print(f"朗读: 还需 {req['need']} 段")
                elif tag == 7:
                    print("阅读进度: 暂未实现自动完成")
            if not any_incomplete:
                print(f"书籍 {book_name} 所有任务已完成！")
                return

            # 讨论发帖
            if tasks.get(0, {}).get("need_topic", 0) > 0:
                need = tasks[0]["need_topic"]
                for i in range(need):
                    print(f"\n--- 讨论发帖 {i+1}/{need} ---")
                    print(f"[话题] {book_name}")
                    content = ai.generate_discuss_topic(book_name) if ai else None
                    if not content:
                        content = random.choice(TEMPLATES["discuss_topic"])
                    print(f"[AI 生成讨论帖]\n{content}")
                    self.add_discuss_topic(book_id, content)
                    random_delay(3)

            # 报告
            if tasks.get(5, {}).get("need", 0) > 0:
                need = tasks[5]["need"]
                for i in range(need):
                    print(f"\n--- 读书报告 {i+1}/{need} ---")
                    print(f"[书名] {book_name}")
                    content = ai.generate_report(book_name) if ai else None
                    if not content:
                        content = TEMPLATES["report"][0]
                    print(f"[AI 生成报告]\n{content}")
                    self.add_topic(book_id, 5, f"Reading Report on {book_name}", content)
                    random_delay(3)

            # 摘抄（随机真实原文）
            if tasks.get(6, {}).get("need", 0) > 0:
                need = tasks[6]["need"]
                # 获取候选句子（带缓存）
                candidates = self._get_excerpt_candidates(book_id)
                for i in range(need):
                    print(f"\n--- 摘抄 {i+1}/{need} ---")
                    if candidates:
                        quote = random.choice(candidates)
                    else:
                        quote = "The magic of the garden healed them all."
                    print(f"[摘抄原文] {quote}")
                    insight = ai.generate_excerpt_insight(quote) if ai else None
                    if not insight:
                        insight = TEMPLATES["excerpt"][0].split("My understanding:")[1].strip()
                    print(f"[AI 见解]\n{insight}")
                    self.add_topic(book_id, 6, f"Excerpt {i+1} from {book_name}", quote, extra_yanwen=insight)
                    random_delay(2)

            # 概要
            if tasks.get(4, {}).get("need", 0) > 0:
                need = tasks[4]["need"]
                for i in range(need):
                    print(f"\n--- 概要 {i+1}/{need} ---")
                    print(f"[书名] {book_name}")
                    content = ai.generate_summary(book_name) if ai else None
                    if not content:
                        content = TEMPLATES["report"][0][:200]
                    print(f"[AI 生成概要]\n{content}")
                    self.add_topic(book_id, 4, f"Summary of {book_name}", content)
                    random_delay(3)

            # 回帖（显示原帖内容）
            if tasks.get(0, {}).get("need_comment", 0) > 0:
                need = tasks[0]["need_comment"]
                all_topics = []
                page = 1
                while len(all_topics) < need and page <= 10:
                    topics, page_total = self.get_topic_list(book_id, 0, page)
                    for t in topics:
                        if t.get("user_id") != self.user_id and t["topic_id"] not in self.replied_topics:
                            all_topics.append(t)
                    if page >= page_total:
                        break
                    page += 1
                    random_delay(1)
                if len(all_topics) < need:
                    print(f"警告：可用的其他用户帖子不足 {need}，只找到 {len(all_topics)} 个")
                selected = random.sample(all_topics, min(need, len(all_topics))) if all_topics else []
                for idx, t in enumerate(selected):
                    print(f"\n--- 回帖 {idx+1}/{len(selected)} ---")
                    full_text = t.get("topic_info") or t.get("topic", "")
                    snippet = full_text[:200].strip()
                    print(f"[原帖 ID={t['topic_id']}] {snippet}{'...' if len(full_text) > 200 else ''}")
                    content = ai.generate_comment(snippet) if ai else None
                    if not content:
                        content = random.choice(TEMPLATES["comment"])
                    print(f"[AI 回复]\n{content}")
                    self.add_comment(book_id, t["topic_id"], content)
                    random_delay(2)

            # 朗读（调用被注释掉的方法，仅打印提示）
            if tasks.get(3, {}).get("need", 0) > 0:
                self.complete_reading(book_id, tasks[3]["need"])

            # 刷新进度
            self.fetch_books()
            for b in self.books:
                if b["book_id"] == book_id:
                    detail = b["detail"]
                    break
            tasks = self.parse_task_requirements(detail, config)
            still_incomplete = any(
                (tag == 0 and (req["need_topic"] > 0 or req["need_comment"] > 0)) or
                (tag in [3,4,5,6] and req["need"] > 0)
                for tag, req in tasks.items()
            )
            if not still_incomplete:
                print(f"书籍 {book_name} 所有任务已完成！")
                return
            print(f"仍有未完成任务，第 {retry+1} 次重试...")
            random_delay(5)
        print(f"书籍 {book_name} 达到最大重试次数，部分任务可能未完成。")

    def run_auto_mode(self, selected_indices: List[int]):
        for idx in selected_indices:
            if 1 <= idx <= len(self.books):
                book = self.books[idx-1]
                self.current_book = book
                self.run_auto_on_book(book)
            else:
                print(f"无效序号 {idx}，跳过")

    def parse_indices(self, input_str: str, total: int) -> List[int]:
        input_str = input_str.strip().lower()
        if input_str == "all":
            return list(range(1, total+1))
        indices = set()
        parts = re.split(r'[ ,]+', input_str)
        for part in parts:
            if not part:
                continue
            if ':' in part:
                try:
                    s, e = map(int, part.split(':'))
                    if s > e: s, e = e, s
                    for i in range(s, e+1):
                        if 1 <= i <= total: indices.add(i)
                except: pass
            else:
                try:
                    i = int(part)
                    if 1 <= i <= total: indices.add(i)
                except: pass
        return sorted(indices)

    # ------------------------- 检测模式交互 -------------------------
    def check_mode(self):
        if not self.current_book:
            print("尚未选择书籍，请使用 select 命令选择。")
        else:
                print("\n检测模式命令:")
                print("  tasks              - 查看任务进度详情")
                print("  topics [页数]      - 查看讨论区帖子列表（默认第1页）")
                print("  chapters [可选]    - 查看章节列表（用于朗读）")
                print("                         章节id 显示该章名称节段落数与总字数")                   
                print("  paragraph <cp_id> [选项] - 查看指定章节的段落内容，支持选项:")
                print("                         -page all|数字|范围 (如: -page 1,3,5:7)")
                print("                         -type all|整数 (显示完整或前N字)")
                print("                         -save 文件夹路径 (保存完整内容)")
                print("  info               - 显示当前书籍基本信息")
                print("  select             - 重新选择书籍")
                print("  auto               - 切换到自动模式（可指定单本或批量）")
                print("  help [命令]        - 显示帮助信息")
                print("  quit               - 退出程序")
                print("输入 help /命令 查看详细用法，如 help /tasks")
        while True:
            cmd = input("\n> ").strip().lower()
            if cmd is None:
                print("\n检测模式命令:")
                print("  tasks              - 查看任务进度详情")
                print("  topics [页数]      - 查看讨论区帖子列表（默认第1页）")
                print("  chapters [可选]    - 查看章节列表（用于朗读）")
                print("                         章节id 显示该章名称节段落数与总字数")                   
                print("  paragraph <cp_id> [选项] - 查看指定章节的段落内容，支持选项:")
                print("                         -page all|数字|范围 (如: -page 1,3,5:7)")
                print("                         -type all|整数 (显示完整或前N字)")
                print("                         -save 文件夹路径 (保存完整内容)")
                print("  info               - 显示当前书籍基本信息")
                print("  select             - 重新选择书籍")
                print("  auto               - 切换到自动模式（可指定单本或批量）")
                print("  help [命令]        - 显示帮助信息")
                print("  quit               - 退出程序")
                print("输入 help /命令 查看详细用法，如 help /tasks")
            if cmd == "help":
                # 显示完整帮助面板
                print("\n检测模式命令:")
                print("  tasks              - 查看任务进度详情")
                print("  topics [页数]      - 查看讨论区帖子列表（默认第1页）")
                print("  chapters [可选]    - 查看章节列表（用于朗读）")
                print("                         章节id 显示该章名称节段落数与总字数")                   
                print("  paragraph <cp_id> [选项] - 查看指定章节的段落内容，支持选项:")
                print("                         -page all|数字|范围 (如: -page 1,3,5:7)")
                print("                         -type all|整数 (显示完整或前N字)")
                print("                         -save 文件夹路径 (保存完整内容)")
                print("  info               - 显示当前书籍基本信息")
                print("  select             - 重新选择书籍")
                print("  auto               - 切换到自动模式（可指定单本或批量）")
                print("  help [命令]        - 显示帮助信息")
                print("  quit               - 退出程序")
                print("输入 help /命令 查看详细用法，如 help /tasks")
            elif cmd.startswith("help "):
                # 处理 help /命令 的子命令帮助
                sub_cmd = cmd[5:].strip().lstrip('/')
                help_details = {
                    "tasks": "显示当前书籍的任务进度，包括讨论、报告、摘抄、朗读等还需完成的次数。",
                    "topics": "查看讨论区的帖子列表，可指定页码。",
                    "chapters": "列出本书所有章节，或输入章节ID查看该章详情。",
                    "paragraph": "查看指定章节(cp_id)的段落内容，支持分页、截断和保存到文件。\n选项：\n  -page all|数字|范围  指定页码或范围\n  -type all|整数      显示完整或前N字\n  -save 路径         保存到指定目录",
                    "info": "显示当前选中书籍的名称和ID。",
                    "select": "重新从书籍列表中选择一本书进行操作。",
                    "auto": "切换到自动模式，选择书籍后自动执行发帖、回帖等任务。",
                    "help": "显示帮助信息。",
                    "quit": "退出程序。",
                }
                if sub_cmd in help_details:
                    print(f"\n命令 {sub_cmd} 的详细帮助:")
                    print(help_details[sub_cmd])
                else:
                    print(f"未知命令 '{sub_cmd}'，输入 help 查看可用命令。")
            elif cmd == "tasks":
                if not self.current_book: continue
                tasks = self.parse_task_requirements(self.current_book["detail"],
                                                     self.current_book["config"])
                print("任务进度详情:")
                for tag, req in tasks.items():
                    if tag == 0:
                        print(f"讨论: 发帖还需 {req['need_topic']} 次, 回帖还需 {req['need_comment']} 次")
                    elif tag in [3,4,5,6]:
                        name = {3:"朗读",4:"概要",5:"报告",6:"摘抄"}.get(tag)
                        print(f"{name}: 还需 {req['need']} 次")
            elif cmd.startswith("topics"):
                parts = cmd.split()
                page = int(parts[1]) if len(parts) > 1 else 1
                if not self.current_book: continue
                topics, tp = self.get_topic_list(self.current_book["book_id"], 0, page)
                print(f"第 {page} 页 / 共 {tp} 页:")
                for i, t in enumerate(topics[:10]):
                    owner = "我" if t.get("user_id") == self.user_id else f"用户{t.get('user_id')}"
                    print(f"{i+1}. [{owner}] {t.get('topic')[:50]}... (ID: {t.get('topic_id')})")
            elif cmd.startswith("chapters"):
                parts = cmd.split()
                if not self.current_book: continue
                if len(parts) > 1:
                    self.show_chapter_stats(parts[1])
                else:
                    chapters, _ = self.get_chapter_list(self.current_book["book_id"])
                    for ch in chapters:
                        print(f"cp_id={ch['cp_id']}, {ch['chapter']}, 字数={ch.get('word','?')}")
            elif cmd == "info":
                if self.current_book:
                    print(f"书籍: {self.current_book['name']} (ID: {self.current_book['book_id']})")
            elif cmd == "select":
                self._select_book()
            elif cmd == "auto":
                print("请输入要处理的书籍编号（支持 all / 数字 / 范围）")
                inp = input("> ").strip()
                indices = self.parse_indices(inp, len(self.books))
                if indices:
                    self.dry_run = False
                    self.run_auto_mode(indices)
            elif cmd == "quit":
                exit(0)
            else:
                print("未知命令")

    def show_chapter_stats(self, cp_id):
        if not self.current_book: return
        try:
            chapters, novel_obj = self.get_chapter_list(self.current_book["book_id"])
            target = next((ch for ch in chapters if str(ch['cp_id']) == cp_id), None)
            if not target:
                print(f"未找到 cp_id={cp_id} 的章节")
                return
            contents = self.get_chapter_content(cp_id, self.current_book["book_id"], novel_obj)
            para_count = sum(1 for item in contents if item.get("type") == "text")
            print(f"\n章节 {cp_id}: {target['chapter']}")
            print(f"总字数: {target.get('word','?')}  段落数: {para_count}")
        except Exception as e:
            print(f"获取章节详情失败: {e}")

    def _select_book(self):
        if not self.books:
            self.books = self.fetch_books()
        print("\n您已加入的书籍列表：")
        for i, b in enumerate(self.books):
            print(f"{i+1}. {b['name']} (ID: {b['book_id']})")
        choice = input("请选择书籍编号: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(self.books):
                self.current_book = self.books[idx]
                print(f"已选择: {self.current_book['name']} (ID: {self.current_book['book_id']})")
            else:
                print("无效编号")
        except ValueError:
            print("请输入数字")

# ======================== 主程序入口 ========================
def main():
    client = HaoCeClient()
    try:
        client.login()
    except Exception as e:
        print(f"登录失败: {e}")
        return
    client.books = client.fetch_books()
    if not client.books:
        print("没有找到任何书籍，请先加入课程。")
        return
    print("\n欢迎使用好策自动化脚本")
    print("1. 检测模式（查看数据、手动操作）")
    print("2. 自动模式（正式执行，会真实发帖/回帖）")
    print("3. 校验模式（模拟执行，展示AI生成内容但不发送请求）")
    mode = input("请选择 (1/2/3): ").strip()
    if mode == "1":
        client._select_book()
        if client.current_book:
            client.check_mode()
    elif mode == "2":
        client.dry_run = False
        print("\n您已加入的书籍列表：")
        for i, b in enumerate(client.books):
            print(f"{i+1}. {b['name']} (ID: {b['book_id']})")
        print("请输入要处理的书籍编号（支持 all / 数字 / 范围如 1,3:5）")
        inp = input("> ").strip()
        indices = client.parse_indices(inp, len(client.books))
        if indices:
            client.run_auto_mode(indices)
        else:
            print("无效输入。")
    elif mode == "3":
        client.dry_run = True
        print("\n[校验模式] 不会发送任何请求，仅模拟并展示 AI 生成内容。")
        print("已加入的书籍列表：")
        for i, b in enumerate(client.books):
            print(f"{i+1}. {b['name']} (ID: {b['book_id']})")
        print("请输入要模拟的书籍编号（支持 all / 数字 / 范围）")
        inp = input("> ").strip()
        indices = client.parse_indices(inp, len(client.books))
        if indices:
            client.run_auto_mode(indices)
        else:
            print("无效输入。")
    else:
        print("无效选择。")

if __name__ == "__main__":
    main()