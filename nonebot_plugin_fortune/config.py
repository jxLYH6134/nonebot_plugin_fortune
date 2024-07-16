import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Union

from nonebot import get_driver
from nonebot.log import logger
from pydantic import BaseModel, Extra, root_validator

from .download import ResourceError, download_resource

"""
	抽签主题对应表，第一键值为“抽签设置”或“主题列表”展示的主题名称
	Key-Value: 主题资源文件夹名-主题别名
"""
FortuneThemesDict: Dict[str, List[str]] = {
    "random": ["随机"],
    "blue_archive": ["蔚蓝档案", "碧蓝档案", "BA", "ba"],
    "yuzusoft": ["柚子社", "柚子", "yuzu"],
    "others": ["其他更多……", "其他"],
}


class PluginConfig(BaseModel, extra=Extra.ignore):
    divine_path: Path = Path(__file__).parent.parent.parent / "resource" / "fortune"
    data_path: Path = Path(__file__).parent.parent.parent / "data" / "fortune"
    github_proxy: str = "https://github.com/"


class ThemesFlagConfig(BaseModel, extra=Extra.ignore):
    """
    Switches of themes only valid in random divination.
    Make sure NOT ALL FALSE!
    """

    blue_archive_flag: bool = True
    yuzusoft_flag: bool = True
    others_flag: bool = True

    @root_validator
    def check_all_disabled(cls, values) -> None:
        """Check whether all themes are DISABLED"""
        flag: bool = False
        for theme in values:
            if values.get(theme, False):
                flag = True
                break

        if not flag:
            raise ValueError("Fortune themes ALL disabled! Please check!")

        return values


class FortuneConfig(PluginConfig, ThemesFlagConfig):
    pass


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj) -> Union[str, Any]:
        if isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(obj, date):
            return obj.strftime("%Y-%m-%d")

        return json.JSONEncoder.default(self, obj)


driver = get_driver()
fortune_config: PluginConfig = PluginConfig.parse_obj(driver.config.dict())
themes_flag_config: ThemesFlagConfig = ThemesFlagConfig.parse_obj(driver.config.dict())


@driver.on_startup
async def fortune_check() -> None:
    if not fortune_config.divine_path.exists():
        fortune_config.divine_path.mkdir(parents=True, exist_ok=True)
    if not fortune_config.data_path.exists():
        fortune_config.data_path.mkdir(parents=True, exist_ok=True)

    """Check fonts"""
    fonts_path: Path = fortune_config.divine_path / "font"
    if not fonts_path.exists():
        fonts_path.mkdir(parents=True, exist_ok=True)

    if not (fonts_path / "Mamelon.otf").is_file():
        raise ResourceError("资源 Mamelon.otf 缺失！请检查！")

    if not (fonts_path / "sakura.ttf").is_file():
        raise ResourceError("资源 sakura.ttf 缺失！请检查！")

    """
		Try to get the latest copywriting from the repository.
	"""
    copywriting_path: Path = (
        fortune_config.divine_path / "fortune" / "copywriting.json"
    )
    if not copywriting_path.parent.exists():
        copywriting_path.parent.mkdir(parents=True, exist_ok=True)

    ret = await download_resource(
        copywriting_path, "copywriting.json", fortune_config.github_proxy, "fortune"
    )
    if not ret and not copywriting_path.exists():
        raise ResourceError("Resource copywriting.json is missing! Please check!")

    """
		Check rules and data files
	"""
    fortune_data_path: Path = fortune_config.data_path / "fortune_data.json"
    # fortune_setting_path: Path = fortune_config.data_path / "fortune_setting.json"
    group_rules_path: Path = fortune_config.data_path / "group_rules.json"
    specific_rules_path: Path = fortune_config.data_path / "specific_rules.json"

    if not fortune_data_path.exists():
        logger.warning("Resource fortune_data.json is missing, initialized one...")

        with fortune_data_path.open("w", encoding="utf-8") as f:
            json.dump(dict(), f, ensure_ascii=False, indent=4)
    else:
        """
        In version 0.4.10, the format of fortune_data.json is changed from v0.4.9 and older.
        1. Remove useless keys "gid", "uid" and "nickname"
        2. Transfer the key "is_divined" to "last_sign_date"
        """
        with open(fortune_data_path, "r", encoding="utf-8") as f:
            _data: Dict[str, Dict[str, Dict[str, Union[str, bool, int, date]]]] = (
                json.load(f)
            )

        for gid in _data:
            if _data[gid]:
                for uid in _data[gid]:
                    """
                    From this time, if is_divined is False, don't care the last sign-in date.
                    Otherwise, the last sign-in date is TODAY.
                    """
                    try:
                        _data[gid][uid].pop("nickname")
                    except KeyError:
                        pass

                    try:
                        _data[gid][uid].pop("gid")
                    except KeyError:
                        pass

                    try:
                        _data[gid][uid].pop("uid")
                    except KeyError:
                        pass

                    try:
                        is_divined: bool = _data[gid][uid].pop(
                            "is_divined"
                        )  # type: ignore
                        if is_divined:
                            _data[gid][uid].update({"last_sign_date": date.today()})
                        else:
                            _data[gid][uid].update({"last_sign_date": 0})
                    except KeyError:
                        pass

        with open(fortune_data_path, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=4, cls=DateTimeEncoder)

    _flag: bool = False
    if not group_rules_path.exists():
        # In version 0.4.x, compatible job will be done automatically if group_rules.json doesn't exist
        # if fortune_setting_path.exists():
        #     # Try to transfer from the old setting json
        #     ret = group_rules_transfer(fortune_setting_path, group_rules_path)
        #     if ret:
        #         logger.info(
        #             "旧版 fortune_setting.json 文件中群聊抽签主题设置已更新至 group_rules.json"
        #         )
        #         _flag = True

        if not _flag:
            # If failed or fortune_setting_path doesn't exist, initialize group_rules.json instead
            with group_rules_path.open("w", encoding="utf-8") as f:
                json.dump(dict(), f, ensure_ascii=False, indent=4)

            # logger.info(
            #     "旧版 fortune_setting.json 文件中群聊抽签主题设置不存在，初始化 group_rules.json"
            # )

    _flag = False
    if not specific_rules_path.exists():
        # In version 0.4.9 and 0.4.10, data transfering will be done automatically if specific_rules.json doesn't exist
        # if fortune_setting_path.exists():
        #     # Try to transfer from the old setting json
        #     ret = specific_rules_transfer(fortune_setting_path, specific_rules_path)
        #     if ret:
        #         # Delete the old fortune_setting json if the transfer is OK
        #         fortune_setting_path.unlink()
        #
        #         logger.info(
        #             "旧版 fortune_setting.json 文件中签底指定规则已更新至 specific_rules.json"
        #         )
        #         # logger.warning("指定签底抽签功能将在 v0.5.0 弃用")
        #         _flag = True

        if not _flag:
            # Try to download it from repo
            ret = await download_resource(
                specific_rules_path, "specific_rules.json", fortune_config.github_proxy
            )
            if ret:
                logger.info("Downloaded specific_rules.json from repo")
            else:
                # If failed, initialize specific_rules.json instead
                with specific_rules_path.open("w", encoding="utf-8") as f:
                    json.dump(dict(), f, ensure_ascii=False, indent=4)

                # logger.info(
                #     "旧版 fortune_setting.json 文件中签底指定规则不存在，初始化 specific_rules.json"
                # )
                # logger.warning("指定签底抽签功能将在 v0.5.0 弃用")


def group_rules_transfer(fortune_setting_dir: Path, group_rules_dir: Path) -> bool:
    """
    Transfer the group_rule in fortune_setting.json to group_rules.json
    """
    with open(fortune_setting_dir, "r", encoding="utf-8") as f:
        _setting: Dict[str, Dict[str, Union[str, List[str]]]] = json.load(f)

    group_rules = _setting.get("group_rule", None)  # Old key is group_rule

    with open(group_rules_dir, "w", encoding="utf-8") as f:
        if group_rules is None:
            json.dump(dict(), f, ensure_ascii=False, indent=4)
            return False
        else:
            json.dump(group_rules, f, ensure_ascii=False, indent=4)
            return True


def specific_rules_transfer(
    fortune_setting_dir: Path, specific_rules_dir: Path
) -> bool:
    """
    Transfer the specific_rule in fortune_setting.json to specific_rules.json
    """
    with open(fortune_setting_dir, "r", encoding="utf-8") as f:
        _setting: Dict[str, Dict[str, Union[str, List[str]]]] = json.load(f)

    specific_rules = _setting.get("specific_rule", None)  # Old key is specific_rule

    with open(specific_rules_dir, "w", encoding="utf-8") as f:
        if not specific_rules:
            json.dump(dict(), f, ensure_ascii=False, indent=4)
            return False
        else:
            json.dump(specific_rules, f, ensure_ascii=False, indent=4)
            return True
