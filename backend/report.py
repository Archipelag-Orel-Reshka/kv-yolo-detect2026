"""Automatic, atomic competition reports. Each new run keeps its own files."""
import csv
import io
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from labels import display_name


class ReportStore:
    def __init__(self, directory, team, names):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.team = team.strip()
        if not self.team:
            raise ValueError("Укажите название команды")
        self.names = list(names)
        self.current = None
        self.error = None
        latest = self.directory / "current.json"
        if latest.exists():
            saved = json.loads(latest.read_text(encoding="utf-8"))
            if (saved["team"] == self.team and set(saved["counts"]) == set(self.names)
                    and all(type(v) is int and v >= 0 for v in saved["counts"].values())
                    and saved["total"] == sum(saved["counts"].values())):
                self.current = saved
        if self.current is None:
            self.new_run({name: 0 for name in self.names})

    def new_run(self, counts):
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.current = {"run_id": datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8],
                        "team": self.team, "started_at": stamp}
        return self.save(counts)

    def save(self, counts):
        """Called while Vision.lock is held, with the same counts shown by the API."""
        self.current.update(team=self.team, counts=dict(counts), total=sum(counts.values()),
                            counts_ru={display_name(name): value for name, value in counts.items()},
                            updated_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        payload = json.dumps(self.current, ensure_ascii=False, indent=2) + "\n"
        txt = (f"Команда: {self.team}\nДата: {self.current['started_at']}\n"
               f"Обновлён: {self.current['updated_at']}\n"
               + "".join(f"{display_name(name)}: {value}\n" for name, value in counts.items())
               + f"Всего: {self.current['total']}\n")
        table = io.StringIO(newline="")
        writer = csv.writer(table, delimiter=";")
        writer.writerow(["Команда", "Дата", *(display_name(name) for name in counts), "Всего"])
        writer.writerow([self.team, self.current["started_at"], *counts.values(), self.current["total"]])
        try:
            stem = "run-" + self.current["run_id"]
            for suffix, data in (("txt", txt.encode("utf-8")),
                                 ("csv", table.getvalue().encode("utf-8-sig")),
                                 ("json", payload.encode("utf-8"))):
                self._atomic(self.directory / f"{stem}.{suffix}", data)
            self._atomic(self.directory / "current.json", payload.encode("utf-8"))
            self.error = None
        except OSError as exc:
            self.error = f"Отчёт не сохранён: {exc}"
        return self.info()

    @staticmethod
    def _atomic(path, data):
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)

    def info(self):
        return {"team": self.team, "run_id": self.current["run_id"],
                "updated_at": self.current.get("updated_at"),
                "directory": str(self.directory), "error": self.error}

    def read(self, format):
        if format not in ("txt", "csv", "json"):
            raise ValueError("Неизвестный формат отчёта")
        return (self.directory / f"run-{self.current['run_id']}.{format}").read_bytes()
