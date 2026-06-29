from ok import TriggerTask


class MyTriggerTask(TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "触发器会不断调用run方法"
        self.description = "一般根据frame来判断是否需要运行"
        self.trigger_count = 0

    def run(self):
        self.trigger_count += 1
        self.log_debug(f'MyTriggerTask run {self.trigger_count}')



