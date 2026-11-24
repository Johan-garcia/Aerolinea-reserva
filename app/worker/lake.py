"""Un prefijo del lago: s3://bucket/prefijo/ en AWS o una carpeta local en desarrollo."""
from __future__ import annotations

import os
from urllib.parse import urlparse


class Lake:
    def __init__(self, uri: str, region: str = "us-east-1"):
        self.uri = uri if uri.endswith("/") else uri + "/"
        self.is_s3 = uri.startswith("s3://")
        self.region = region
        self._s3 = None
        if self.is_s3:
            u = urlparse(self.uri)
            self.bucket, self.prefix = u.netloc, u.path.lstrip("/")
        else:
            self.root = self.uri
            os.makedirs(self.root, exist_ok=True)

    @property
    def s3(self):
        if self._s3 is None:
            import boto3
            self._s3 = boto3.client("s3", region_name=self.region)
        return self._s3

    def uri_for(self, rel: str) -> str:
        return self.uri + rel

    def put(self, rel: str, data: bytes, content_type: str = "application/octet-stream"):
        if self.is_s3:
            self.s3.put_object(Bucket=self.bucket, Key=self.prefix + rel, Body=data, ContentType=content_type)
        else:
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)    # atómico: un lector nunca ve un archivo a medias

    def upload_file(self, local_path: str, rel: str):
        if self.is_s3:
            self.s3.upload_file(local_path, self.bucket, self.prefix + rel)
        else:
            with open(local_path, "rb") as fh:
                self.put(rel, fh.read())

    def list(self, sub: str = "") -> list[str]:
        """Claves relativas al prefijo (ignora temporales y archivos ocultos)."""
        out = []
        if self.is_s3:
            pag = self.s3.get_paginator("list_objects_v2")
            for page in pag.paginate(Bucket=self.bucket, Prefix=self.prefix + sub):
                out += [o["Key"][len(self.prefix):] for o in page.get("Contents", [])]
        else:
            base = os.path.join(self.root, sub)
            for dp, _, files in os.walk(base if os.path.isdir(base) else self.root):
                for f in files:
                    if f.endswith(".tmp") or f.startswith("."):
                        continue
                    rel = os.path.relpath(os.path.join(dp, f), self.root).replace(os.sep, "/")
                    if rel.startswith(sub):
                        out.append(rel)
        return sorted(out)

    def get(self, rel: str) -> bytes:
        if self.is_s3:
            return self.s3.get_object(Bucket=self.bucket, Key=self.prefix + rel)["Body"].read()
        with open(os.path.join(self.root, rel), "rb") as fh:
            return fh.read()

    def delete(self, rels: list[str]):
        if not rels:
            return
        if self.is_s3:
            for i in range(0, len(rels), 1000):
                self.s3.delete_objects(Bucket=self.bucket, Delete={
                    "Objects": [{"Key": self.prefix + r} for r in rels[i:i + 1000]], "Quiet": True})
        else:
            for r in rels:
                try:
                    os.remove(os.path.join(self.root, r))
                except FileNotFoundError:
                    pass
