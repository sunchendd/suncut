"""hub —— 进程级基础设施:stdout 分发器(PrintHub)+ 事件总线(EventBus)+ WS 连接池.

PrintHub 解决的核心问题: sd/ 全部用 print() 输出进度,而服务端多个任务线程并发时,
contextlib.redirect_stdout 是进程全局的会互相串。改为按"发起线程"分发:
任务线程绑定的 Job 收走该线程的所有 print,其余线程(含 uvicorn)原样放行。
"""
import asyncio
import json
import sys
import threading
import time


class PrintHub:
    """接管 sys.stdout,把 print 行按线程归属分发到 Job.log / 原终端."""

    def __init__(self):
        self.orig = sys.stdout
        self._jobs = {}          # thread ident -> Job
        self._lock = threading.Lock()

    def install(self):
        sys.stdout = self

    def bind(self, job):
        with self._lock:
            self._jobs[threading.get_ident()] = job

    def unbind(self):
        with self._lock:
            self._jobs.pop(threading.get_ident(), None)

    # file 协议
    def write(self, s):
        job = self._jobs.get(threading.get_ident())
        if job is not None:
            job.log_write(s)
            return len(s)
        return self.orig.write(s)

    def flush(self):
        try:
            self.orig.flush()
        except Exception:
            pass

    def isatty(self):
        return False


class EventBus:
    """同步发布 -> 异步消费:工作线程 publish,事件循环侧 broadcast 到所有 WS."""

    def __init__(self):
        self._loop = None
        self._clients = set()      # asyncio WebSocket
        self._lock = threading.Lock()

    def attach_loop(self, loop):
        self._loop = loop

    def connect(self, ws):
        with self._lock:
            self._clients.add(ws)

    def disconnect(self, ws):
        with self._lock:
            self._clients.discard(ws)

    def publish(self, type_, **payload):
        """任意线程可调;无 WS 或无循环时静默丢弃."""
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast({"type": type_, **payload}),
                                             self._loop)
        except RuntimeError:
            pass

    async def _broadcast(self, msg):
        data = json.dumps(msg, ensure_ascii=False, default=str)   # Path 等安全序列化
        dead = []
        with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


class Heartbeat:
    """25s 心跳,防中间设备掐空闲 WS(showvi 同款间隔)."""

    def __init__(self, bus):
        self.bus = bus

    async def run(self):
        while True:
            await asyncio.sleep(25)
            self.bus.publish("ping", t=time.strftime("%F %T"))


print_hub = PrintHub()
bus = EventBus()
