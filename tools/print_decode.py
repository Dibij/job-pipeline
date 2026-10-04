import inspect
import laya.agent

src = inspect.getsource(laya.agent.Agent._decode_answers)
print(src)
