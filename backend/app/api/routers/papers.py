"""论文接口：列表筛选 / 详情 / 手工 CRUD / PDF Range 流式（4.4、6.1）。"""
import re

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from urllib.parse import unquote

from app.api.deps import get_db
from app.api.filtering import PAPER_SORTS, PaperFilters, bad_request, paper_filters, paper_query
from app.api.schemas import PaperCreateRequest, PaperPatchRequest
from app.api.serializers import abstract_text, arxiv_url, authors_for, directions_for, doi_url, paper_card, paper_links, paper_mode
from app.config import settings
from app.models import Author, Direction, Paper, PaperAuthor, PaperDirection, Venue

router = APIRouter(prefix="/api/papers", tags=["papers"])

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
_bad_request = bad_request


@router.get("")
def list_papers(
    filters: PaperFilters = Depends(paper_filters),
    sort: str = "created_desc",
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
):
    if page < 1 or not 1 <= size <= 100:
        raise _bad_request("page>=1 且 1<=size<=100")
    if sort not in PAPER_SORTS:
        raise _bad_request("sort 仅支持 year_desc|citation_desc|created_desc")
    query = paper_query(db, filters)
    total = query.count()
    items = (
        query.order_by(*PAPER_SORTS[sort])
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    directions = directions_for(db, [p.id for p in items])
    authors = authors_for(db, [p.id for p in items])
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [paper_card(p, directions, authors) for p in items],
    }


@router.post("", status_code=201)
def create_paper(body: PaperCreateRequest, db: Session = Depends(get_db)):
    venue = db.query(Venue).filter(
        Venue.abbr == body.venue_abbr, Venue.ccf_level.in_(("A", "B")),
        Venue.type.in_(("conf", "journal")),
    ).one_or_none()
    if venue is None:
        raise _bad_request("venue_abbr 不在配置的 A/B 来源中")
    doi_link = doi_url(body.doi)
    doi = unquote(doi_link.removeprefix("https://doi.org/")) if doi_link else None
    arxiv_link = arxiv_url(body.arxiv_id)
    arxiv_id = arxiv_link.removeprefix("https://arxiv.org/abs/") if arxiv_link else None
    if body.dblp_key and not body.dblp_key.startswith(venue.dblp_stream + "/"):
        raise _bad_request("dblp_key 与所选 venue 不匹配")
    for column, value in ((Paper.dblp_key, body.dblp_key), (Paper.doi, doi), (Paper.arxiv_id, arxiv_id)):
        if value and db.query(Paper.id).filter(column == value).first():
            raise HTTPException(409, detail={"code": "DUPLICATE", "message": "该论文标识已存在"})
    paper = Paper(
        source="dblp" if body.dblp_key else "manual",
        dblp_key=body.dblp_key, title=body.title, title_norm=_norm_title(body.title),
        venue_id=venue.id, year=body.year, ccf_level=venue.ccf_level, ccf_area=venue.ccf_area,
        doi=doi, arxiv_id=arxiv_id,
        official_url=doi_link or arxiv_link or "https://dblp.org/rec/" + body.dblp_key,
        oa_url=arxiv_link,
        pdf_status="pending" if settings.pdf_download_enabled else "closed",
        venue_confirmed=0,
    )
    db.add(paper)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail={"code": "DUPLICATE", "message": "该论文标识已存在"}) from exc
    db.refresh(paper)
    return JSONResponse(status_code=201, content={"id": paper.id}, headers={"Location": f"/api/papers/{paper.id}"})


def _norm_title(title: str) -> str:
    from app.cleaning import normalize_title

    return normalize_title(title)



@router.get("/{paper_id}")
def get_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = paper_query(db, PaperFilters()).filter(Paper.id == paper_id).one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail={"code": "PAPER_NOT_FOUND", "message": "论文不存在"})
    venue = paper.venue
    directions = (
        db.query(PaperDirection, Direction)
        .join(Direction, PaperDirection.direction_id == Direction.id)
        .filter(PaperDirection.paper_id == paper.id)
        .all()
    )
    authors = (
        db.query(PaperAuthor, Author)
        .join(Author, PaperAuthor.author_id == Author.id)
        .filter(PaperAuthor.paper_id == paper.id)
        .order_by(PaperAuthor.author_order)
        .all()
    )
    return {
        "id": paper.id,
        "title": paper.title,
        "title_norm": paper.title_norm,
        "abstract": abstract_text(paper.abstract),
        "authors": [{"name": a.name, "order": pa.author_order} for pa, a in authors],
        "venue": {"abbr": venue.abbr, "name": venue.name, "type": venue.type, "level": venue.ccf_level},
        "directions": [
            {"code": d.code, "name": d.name, "score": pd.score, "source": pd.source}
            for pd, d in directions
        ],
        "year": paper.year,
        "citation_count": paper.citation_count,
        "pdf_status": paper.pdf_status,
        "pdf_source": paper.pdf_source,
        "pdf_url": f"/api/papers/{paper.id}/pdf",
        "mode": paper_mode(),
        **paper_links(paper),
        "doi": paper.doi,
        "arxiv_id": paper.arxiv_id,
        "dblp_key": paper.dblp_key,
        "venue_confirmed": paper.venue_confirmed,
        "publication_date": paper.publication_date,
        "note": paper.note,
        "created_at": paper.created_at,
        "updated_at": paper.updated_at,
    }


@router.patch("/{paper_id}")
def patch_paper(paper_id: int, body: PaperPatchRequest, db: Session = Depends(get_db)):
    paper = db.query(Paper).filter(Paper.id == paper_id).one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail={"code": "PAPER_NOT_FOUND", "message": "论文不存在"})
    if body.directions is not None:
        codes = set(body.directions)
        found = db.query(Direction).filter(Direction.code.in_(codes)).all()
        if len(found) != len(codes):
            raise _bad_request("存在未知 direction code")
        existing = db.query(PaperDirection).filter(PaperDirection.paper_id == paper_id).all()
        keep_ids = {direction.id for direction in found}
        existing_ids = {row.direction_id for row in existing}
        for row in existing:
            if row.direction_id in keep_ids:
                row.source = "manual"
            else:
                db.delete(row)
        for direction in found:
            if direction.id not in existing_ids:
                db.add(PaperDirection(paper_id=paper_id, direction_id=direction.id, score=0.0, source="manual"))
    if "note" in body.model_fields_set:
        paper.note = body.note
    db.commit()
    directions = (
        db.query(Direction.code)
        .join(PaperDirection, PaperDirection.direction_id == Direction.id)
        .filter(PaperDirection.paper_id == paper_id)
        .all()
    )
    return {"id": paper_id, "directions": sorted(code for (code,) in directions)}


@router.delete("/{paper_id}", status_code=204)
def delete_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.query(Paper).filter(Paper.id == paper_id).one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail={"code": "PAPER_NOT_FOUND", "message": "论文不存在"})
    # 删除元数据不删除文件；已有存档可由用户检查后单独清理。
    db.delete(paper)
    db.commit()


@router.get("/{paper_id}/pdf")
def get_pdf(
    paper_id: int,
    download: bool = False,
    range_header: str | None = Header(default=None, alias="Range"),
    db: Session = Depends(get_db),
):
    paper = db.query(Paper).filter(Paper.id == paper_id).one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail={"code": "PAPER_NOT_FOUND", "message": "论文不存在"})
    if paper.pdf_status == "closed":
        # 版权策略固化在接口层：未归档 PDF 一律不给流，仅提示合法展示路径
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PDF_CLOSED",
                "message": "该论文为闭源出版，未归档 PDF",
                **paper_links(paper),
            },
        )

    path = (settings.papers_root / paper.pdf_path) if paper.pdf_path else None
    if path is None:
        raise HTTPException(status_code=404, detail={"code": "PDF_NOT_FOUND", "message": "PDF 未就绪"})
    root = settings.papers_root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        # 路径越界一律 404，不泄露目录结构（6.4）
        raise HTTPException(status_code=404, detail={"code": "PDF_NOT_FOUND", "message": "PDF 未就绪"})

    size = resolved.stat().st_size
    start, end = 0, size - 1
    status_code = 200
    if range_header:
        m = _RANGE_RE.match(range_header.strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1) == "":
                # bytes=-N：末尾 N 字节
                suffix = int(m.group(2))
                start = max(0, size - suffix)
                end = size - 1
            else:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
            if start > end or start >= size:
                raise HTTPException(
                    status_code=416,
                    detail={"code": "RANGE_NOT_SATISFIABLE", "message": "Range 不满足"},
                    headers={"Content-Range": f"bytes */{size}"},
                )
            status_code = 206

    from fastapi.responses import StreamingResponse

    def _stream(begin: int, stop: int):
        with resolved.open("rb") as fh:
            fh.seek(begin)
            remaining = stop - begin + 1
            while remaining > 0:
                buf = fh.read(min(65536, remaining))
                if not buf:
                    break
                remaining -= len(buf)
                yield buf

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "application/pdf",
        "Cache-Control": "public, max-age=86400",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    content_length = end - start + 1
    headers["Content-Length"] = str(content_length)
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{paper.id:06d}.pdf"'
    return StreamingResponse(
        _stream(start, end),
        status_code=status_code,
        headers=headers,
        media_type="application/pdf",
    )
