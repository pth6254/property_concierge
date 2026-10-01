import type { ChatSource } from "@/lib/types";

export default function LawSources({ sources }: { sources?: ChatSource[] }) {
  if (!sources?.length) return null;
  return <div className="mt-2 border-t border-slate-200 pt-2 text-xs">
    <p className="mb-1 text-slate-500">참고 근거</p>
    {sources.map((source, index) => {
      const officialUrl = source.url && /^https:\/\/(www\.)?law\.go\.kr\//.test(source.url) ? source.url : undefined;
      return <div key={`${source.title}-${index}`} className="mb-2">
        {officialUrl ? <a href={officialUrl} target="_blank" rel="noopener noreferrer" className="text-primary underline">{source.title} · 원문 보기</a> : <span>{source.title}</span>}
        <div className="text-slate-500">{source.source}{source.effective_date && ` · 시행 ${source.effective_date}`}{source.collected_at && ` · 수집 ${source.collected_at.slice(0, 10)}`}</div>
      </div>;
    })}
  </div>;
}
