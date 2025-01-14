#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# @author by wangcw @ 2025
# @generate at 2025/1/14 15:59
# comment:

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.clock import Clock
import asyncio
from racebox_script import download_racebox_data


class RaceBoxApp(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.status_label = Label(text="欢迎使用 RaceBox 数据下载工具", size_hint=(1, 0.8))
        self.add_widget(self.status_label)

        self.download_button = Button(text="开始下载", size_hint=(1, 0.2))
        self.download_button.bind(on_press=self.start_download)
        self.add_widget(self.download_button)

    def start_download(self, instance):
        self.status_label.text = "正在扫描设备，请稍候..."
        self.download_button.disabled = True
        asyncio.run(self.download_data())

    async def download_data(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.update_status, "开始蓝牙扫描...")
        await download_racebox_data(self.update_status)
        Clock.schedule_once(lambda dt: self.enable_button(), 0)

    def update_status(self, message):
        self.status_label.text = message

    def enable_button(self):
        self.download_button.disabled = False


class RaceBoxAppMain(App):
    def build(self):
        return RaceBoxApp()


if __name__ == "__main__":
    RaceBoxAppMain().run()