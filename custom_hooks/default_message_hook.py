'''
默认的一个扩展上下文脚本, 在custom_hooks目录下添加脚本并编写函数:
- hook_tag_name
- hook_message
每个最新的UserMessage都会附加hook消息, 如最新消息为"现在几点了",
那么在仅有本脚本的情况下上下文会呈现:
f"现在几点了<im_{hook_tag_name()}_start>{hook_message()}</im_{hook_tag_name()}_end>"

被附加的块称为扩展上下文, 这些块仅会在发送会话时附加在最后一条UserMessage的末尾,
这些块既不会出现在持久化的会话的历史记录文件中, 
也不会在下一轮对话中被保留在那个成为倒数第二个UserMessage的末尾,
而只会出现在最后一轮对话的UserMessage的末尾.
'''

import json
from datetime import datetime
import os
import sys
from pathlib import Path


def hook_tag_name() -> str:
    return "external_knowledge"

def hook_message() -> str:
    return json.dumps({
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "current_platform": sys.platform,
        "current_root_dir": Path(__file__).parent.parent.absolute().as_posix(),
    })

if __name__ == "__main__":
    print(f"<im_{hook_tag_name()}_start>{hook_message()}</im_{hook_tag_name()}_end>")