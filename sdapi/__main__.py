"""python3 -m sdapi —— 直接启动工作台服务(等价 uvicorn 命令)."""
import uvicorn

from . import config as svc_config


def main():
    uvicorn.run("sdapi.server:app", host=svc_config.HOST, port=svc_config.PORT,
                workers=1, log_level="info")


if __name__ == "__main__":
    main()
