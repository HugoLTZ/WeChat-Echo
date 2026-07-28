"""
账号管理模块。

管理账号卡片数据的增删改查，使用 JSON 文件持久化存储。
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger("account_manager")

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class Account:
    """单个账号的数据模型。"""

    def __init__(
        self,
        name: str,
        account_id: str = "",
        credential_dir: str = "",
        last_login: str = "",
        remark: str = "",
    ) -> None:
        self.id: str = account_id or uuid.uuid4().hex[:12]
        self.name: str = name
        self.credential_dir: str = credential_dir
        self.last_login: str = last_login
        self.remark: str = remark
        self._online: bool = False

    # ---- computed ----

    @property
    def is_online(self) -> bool:
        return self._online

    @is_online.setter
    def is_online(self, v: bool) -> None:
        self._online = v

    @property
    def has_credentials(self) -> bool:
        """凭证备份文件是否存在。"""
        if not self.credential_dir:
            return False
        p = Path(self.credential_dir)
        return (p / "global_config").is_file() and (p / "global_config.crc").is_file()

    @property
    def credential_status(self) -> str:
        """凭证状态文字。"""
        if not self.has_credentials:
            return "未备份"
        # 简单判断：文件存在即视为有效（实际有效性由微信启动后验证）
        return "已备份"

    # ---- serialisation ----

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "credential_dir": self.credential_dir,
            "last_login": self.last_login,
            "remark": self.remark,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        return cls(
            name=data.get("name", ""),
            account_id=data.get("id", ""),
            credential_dir=data.get("credential_dir", ""),
            last_login=data.get("last_login", ""),
            remark=data.get("remark", ""),
        )

    def __repr__(self) -> str:
        return f"<Account id={self.id} name={self.name!r}>"


class AccountManager:
    """
    账号管理器。

    存储位置：{root_data_dir}/config/accounts.json
    """

    def __init__(self, accounts_file: Path, credentials_root: Path) -> None:
        self._file = accounts_file
        self._credentials_root = credentials_root
        self._accounts: dict[str, Account] = {}

    # ---- CRUD ----

    def add(self, name: str, remark: str = "") -> Account:
        """添加账号。"""
        acc = Account(name=name, remark=remark)
        acc.credential_dir = str(self._credentials_root / f"acc_{acc.id}")
        self._accounts[acc.id] = acc
        self._save()
        logger.info("添加账号: %s (id=%s)", name, acc.id)
        return acc

    def remove(self, account_id: str) -> bool:
        """删除账号。"""
        if account_id not in self._accounts:
            logger.warning("删除失败：账号不存在 id=%s", account_id)
            return False
        name = self._accounts[account_id].name
        del self._accounts[account_id]
        self._save()
        logger.info("删除账号: %s (id=%s)", name, account_id)
        return True

    def get(self, account_id: str) -> Optional[Account]:
        """按 ID 获取账号。"""
        return self._accounts.get(account_id)

    def list_all(self) -> list[Account]:
        """返回所有账号列表（按名称排序）。"""
        return sorted(self._accounts.values(), key=lambda a: a.name)

    def update(self, account_id: str, **kwargs) -> bool:
        """更新账号字段（name, remark, credential_dir 等）。"""
        acc = self._accounts.get(account_id)
        if not acc:
            return False
        for k, v in kwargs.items():
            if hasattr(acc, k):
                setattr(acc, k, v)
        self._save()
        return True

    def mark_logged_in(self, account_id: str) -> None:
        """标记账号已登录（更新时间戳）。"""
        acc = self._accounts.get(account_id)
        if acc:
            acc.last_login = datetime.now().strftime(DATE_FORMAT)
            self._save()

    def search(self, keyword: str) -> list[Account]:
        """按关键词搜索账号（名称 + 备注）。"""
        kw = keyword.strip().lower()
        if not kw:
            return self.list_all()
        return sorted(
            [a for a in self._accounts.values() if kw in a.name.lower() or kw in a.remark.lower()],
            key=lambda a: a.name,
        )

    # ---- persistence ----

    def load(self) -> None:
        """从 JSON 文件加载。"""
        if self._file.is_file():
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data.get("accounts", []):
                    acc = Account.from_dict(item)
                    self._accounts[acc.id] = acc
                logger.info("已加载 %d 个账号", len(self._accounts))
            except (json.JSONDecodeError, OSError) as e:
                logger.error("加载账号文件失败: %s", e)
                self._accounts = {}

    def _save(self) -> None:
        """保存到 JSON 文件。"""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = {"accounts": [a.to_dict() for a in self._accounts.values()]}
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
