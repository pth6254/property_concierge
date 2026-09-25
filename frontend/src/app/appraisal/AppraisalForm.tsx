"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { removeSessionValue, setSessionValue, useSessionValue } from "@/lib/sessionStore";

const PROPERTY_TYPES = [
  { category: "주거용", detail: "아파트",     label: "아파트",          hasDong: true,  hasHo: true  },
  { category: "주거용", detail: "오피스텔",   label: "오피스텔",        hasDong: true,  hasHo: true  },
  { category: "주거용", detail: "연립다세대", label: "빌라 / 연립",     hasDong: false, hasHo: true  },
  { category: "주거용", detail: "단독다가구", label: "단독 / 다가구",   hasDong: false, hasHo: false },
  { category: "상업용", detail: "상가",       label: "상가",            hasDong: false, hasHo: true  },
  { category: "업무용", detail: "사무실",     label: "사무실 / 오피스", hasDong: false, hasHo: true  },
  { category: "산업용", detail: "공장",       label: "공장",            hasDong: false, hasHo: false },
  { category: "산업용", detail: "창고",       label: "창고",            hasDong: false, hasHo: false },
  { category: "토지",   detail: "토지",       label: "토지",            hasDong: false, hasHo: false },
] as const;

type PropertyType = (typeof PROPERTY_TYPES)[number];
type KakaoDoc = {
  place_name?: string;
  address_name?: string;
  road_address_name?: string;
};

const STEPS = ["물건 종류", "주소 입력", "상세 정보"];
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;
const PENDING_JOB_KEY = "appraisalPendingJob";

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

export default function AppraisalForm({ caseId, candidateId }: { caseId?: number; candidateId?: number }) {
  const router = useRouter();
  const [step, setStep] = useState(1);

  // step 1
  const [selectedType, setSelectedType] = useState<PropertyType | null>(null);

  // step 2
  //
  // 홈 컨시어지 데스크에서 넘어온 검색어를 프리필한다. 이전에는 useEffect 에서
  // sessionStorage 를 읽어 setSearchQuery 를 호출했는데, effect 안의 동기
  // setState 라 연쇄 렌더를 유발했다(react-hooks/set-state-in-effect).
  //
  // 대신 "사용자가 입력한 값(typedQuery)이 있으면 그것을, 없으면 넘겨받은
  // 검색어를" 쓰는 파생 값으로 만든다. 페이지를 서버에서 그릴 때는
  // heroQuery 가 undefined 라 빈 문자열이 되므로, 폼 자체는 그대로
  // 서버 렌더된다(게이트를 걸어 페이지를 통째로 비우지 않는다).
  const heroQuery = useSessionValue("heroQuery");
  const [typedQuery, setTypedQuery] = useState<string | null>(null);
  const searchQuery = typedQuery ?? heroQuery ?? "";
  const setSearchQuery = setTypedQuery;
  const [searchResults, setSearchResults] = useState<KakaoDoc[]>([]);
  const [searching, setSearching]         = useState(false);
  const [selectedAddress, setSelectedAddress] = useState("");
  const [buildingName, setBuildingName]   = useState("");
  const [areaSqm, setAreaSqm] = useState("");
  const [prefillLoading, setPrefillLoading] = useState(Boolean(caseId || candidateId));
  const [prefillError, setPrefillError] = useState("");
  const [manualInput, setManualInput]     = useState(false);

  // step 3
  const [dongNo, setDongNo]             = useState("");
  const [hoNo, setHoNo]                 = useState("");
  const [transactionType, setTransactionType] = useState("매매");
  const [appraisalDateType, setAppraisalDateType] = useState<"current" | "custom">("current");
  const [customDate, setCustomDate]     = useState("");          // YYYY-MM-DD
  const [appraisalPurpose, setAppraisalPurpose] = useState(""); // 목적

  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");
  const [progressStep, setProgressStep] = useState(""); // 파이프라인 현재 노드명
  const pendingJob = useSessionValue(PENDING_JOB_KEY);
  const resumingRef = useRef(false);

  // 폴링 취소용 — 페이지를 벗어나면 진행 중인 요청과 대기를 즉시 중단한다.
  // (없으면 다른 메뉴로 이동해도 2초마다 API를 계속 호출하는 유령 폴링이 남는다)
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!caseId && !candidateId) return;
    let cancelled = false;
    (async () => {
      try {
        if (!caseId || !candidateId) throw new Error("잘못된 후보 연결입니다.");
        const value = await api.caseOne(caseId);
        const candidate = value.properties?.find((item) => item.id === candidateId);
        if (!candidate) throw new Error("후보를 찾을 수 없습니다.");
        if (cancelled) return;
        const labels: Record<string, string> = { apartment: "아파트", officetel: "오피스텔", row_house: "연립다세대", detached: "단독다가구", land: "토지" };
        const type = PROPERTY_TYPES.find((item) => item.detail === (labels[candidate.category] ?? candidate.category));
        setSelectedAddress(candidate.address ?? "");
        setBuildingName(candidate.name);
        setTypedQuery(candidate.address ?? "");
        setAreaSqm(candidate.area_sqm == null ? "" : String(candidate.area_sqm));
        if (type) { setSelectedType(type); setStep(candidate.address ? 3 : 2); }
      } catch {
        if (!cancelled) setPrefillError("후보 정보를 불러오지 못했습니다. 케이스에서 다시 열어주세요.");
      } finally { if (!cancelled) setPrefillLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [caseId, candidateId]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // 프리필 값은 페이지를 떠날 때 지운다 — 나중에 /appraisal 에 다시 들어왔을 때
  // 예전 검색어가 또 채워지지 않도록. 마운트 시점에 지우면 heroQuery 가 null 이
  // 되어 위 파생 값이 빈 문자열로 되돌아가므로(= 입력창이 스스로 비워짐)
  // 반드시 언마운트에서 지워야 한다.
  useEffect(() => {
    return () => removeSessionValue("heroQuery");
  }, []);

  const handleAddressSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const result = await api.addressSearch(searchQuery) as { documents: KakaoDoc[] };
      setSearchResults(result.documents || []);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const selectAddress = (doc: KakaoDoc) => {
    setSelectedAddress(doc.road_address_name || doc.address_name || "");
    if (doc.place_name) setBuildingName(doc.place_name);
    setSearchResults([]);
    setSearchQuery("");
    setStep(3);
  };

  const buildUserInput = () => {
    const parts: string[] = [];
    if (selectedType) parts.push(selectedType.detail);
    if (selectedAddress) parts.push(selectedAddress);
    if (buildingName) parts.push(buildingName);
    if (areaSqm) parts.push(`${areaSqm}㎡`);
    if (dongNo) parts.push(dongNo);
    if (hoNo)   parts.push(hoNo);
    parts.push(transactionType);
    if (appraisalDateType === "custom" && customDate) {
      const d = new Date(customDate);
      parts.push(`${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 기준`);
    }
    return parts.join(" ");
  };

  const getAppraisalDate = (): string => {
    if (appraisalDateType === "custom" && customDate) {
      return customDate.replace(/-/g, ""); // YYYYMMDD
    }
    return "";
  };

  const pollJob = useCallback(async (jobId: string, query: string, signal: AbortSignal) => {
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    while (Date.now() < deadline) {
      await sleep(POLL_INTERVAL_MS, signal);
      const job = await api.appraisalJob(jobId, signal);
      if (job.step) setProgressStep(job.step);
      if (job.status === "done") {
        removeSessionValue(PENDING_JOB_KEY);
        if (job.result) {
          setSessionValue("appraisalResult", JSON.stringify(job.result));
          setSessionValue("appraisalQuery", query);
        }
        router.push(job.history_id ? `/report/${job.history_id}` : "/report");
        return;
      }
      if (job.status === "error") {
        removeSessionValue(PENDING_JOB_KEY);
        setError(job.error || "시세추정 실패");
        return;
      }
    }
    setError("시세추정이 예상보다 오래 걸립니다. 새로고침하면 같은 작업을 다시 확인합니다.");
  }, [router]);

  useEffect(() => {
    if (!pendingJob || resumingRef.current) return;
    let saved: { jobId: string; query: string; caseId?: number; candidateId?: number };
    try { saved = JSON.parse(pendingJob); } catch { removeSessionValue(PENDING_JOB_KEY); return; }
    if (saved.caseId !== caseId || saved.candidateId !== candidateId) return;
    resumingRef.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setLoading(true);
      return pollJob(saved.jobId, saved.query, controller.signal);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "작업 조회 실패");
    }).finally(() => { resumingRef.current = false; if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pendingJob, caseId, candidateId, pollJob]);

  const handleSubmit = async () => {
    if (prefillLoading || prefillError) return;
    if (areaSqm && (!Number.isFinite(Number(areaSqm)) || Number(areaSqm) <= 0)) { setError("면적은 0보다 큰 숫자로 입력해주세요."); return; }
    if (!selectedAddress) { setError("주소를 입력해주세요."); return; }
    setError("");
    setLoading(true);
    setProgressStep("");

    abortRef.current?.abort();               // 이전 실행이 남아 있으면 정리
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    try {
      const userInput = buildUserInput();

      // 1) 작업 시작 → job_id
      const { job_id } = await api.appraisalJobStart(
        userInput,
        buildingName,
        true,
        getAppraisalDate(),
        appraisalPurpose,
        selectedAddress,
        selectedType?.category ?? "",
        selectedType?.detail ?? "",
        caseId,
        candidateId,
        areaSqm ? Number(areaSqm) : undefined,
      );
      resumingRef.current = true;
      setSessionValue(PENDING_JOB_KEY, JSON.stringify({ jobId: job_id, query: userInput, caseId, candidateId }));
      await pollJob(job_id, userInput, signal);
    } catch (e: unknown) {
      // 페이지 이탈로 인한 취소는 사용자에게 보여줄 오류가 아니다
      if (signal.aborted) return;
      setError(e instanceof Error ? e.message : "시세추정 실패");
    } finally {
      resumingRef.current = false;
      if (!signal.aborted) setLoading(false);
    }
  };

  const goBack = () => setStep(s => s - 1);

  return (
    <div className="max-w-2xl mx-auto">
      <fieldset disabled={prefillLoading || Boolean(prefillError)} className="min-w-0">
      <h1 className="text-2xl font-bold mb-1">AI 시세추정</h1>
      {prefillLoading && <p role="status">후보 정보를 불러오는 중입니다.</p>}
      {prefillError && <p role="alert" className="text-red-600">{prefillError}</p>}
      {caseId && candidateId && !prefillLoading && !prefillError && <p className="mb-3 text-sm text-primary">후보 정보를 채웠습니다. 주소·면적·물건 종류를 확인해주세요. <a href={`/cases/${caseId}`} className="underline">후보로 돌아가기</a></p>}
      <p className="text-slate-500 mb-5 text-sm">물건 정보를 단계별로 입력하면 AI가 실거래 데이터 기반으로 시세를 추정합니다.</p>

      {/* 스텝 인디케이터 */}
      <div className="flex items-center gap-1 mb-6">
        {STEPS.map((label, i) => {
          const s = i + 1;
          const active  = step === s;
          const done    = step > s;
          return (
            <div key={s} className="flex items-center gap-1 flex-1">
              <div className={`flex items-center gap-2 flex-1 py-2 px-3 rounded-lg text-sm transition-colors ${
                active ? "bg-primary text-white font-semibold" :
                done   ? "bg-emerald-100 text-primary-strong" :
                         "bg-slate-100 text-slate-400"
              }`}>
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                  active ? "bg-white text-primary" :
                  done   ? "bg-primary/60 text-white" :
                           "bg-slate-300 text-slate-500"
                }`}>{s}</span>
                <span className="truncate">{label}</span>
              </div>
              {s < STEPS.length && (
                <div className={`w-3 h-0.5 shrink-0 ${done ? "bg-primary/60" : "bg-slate-200"}`} />
              )}
            </div>
          );
        })}
      </div>

      {/* ── STEP 1 : 물건 종류 선택 ──────────────────── */}
      {step === 1 && (
        <section className="bg-white rounded-xl shadow p-6">
          <h2 className="font-semibold text-base text-slate-800 mb-4">어떤 종류의 부동산인가요?</h2>
          <div className="grid grid-cols-3 gap-3">
            {PROPERTY_TYPES.map(pt => (
              <button
                key={pt.detail}
                onClick={() => { setSelectedType(pt); setStep(2); }}
                className="p-4 rounded-xl border-2 border-slate-200 hover:border-primary hover:bg-emerald-50 text-left transition-colors group"
              >
                <div className="font-semibold text-sm text-slate-800 group-hover:text-primary-strong">{pt.label}</div>
                <div className="text-xs text-slate-400 mt-0.5">{pt.category}</div>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* ── STEP 2 : 주소 입력 ───────────────────────── */}
      {step === 2 && (
        <section className="bg-white rounded-xl shadow p-6">
          <button onClick={goBack} className="text-sm text-slate-400 hover:text-slate-700 mb-4 flex items-center gap-1 transition-colors">
            ← 뒤로
          </button>

          <h2 className="font-semibold text-base text-slate-800 mb-1">
            {selectedType?.label} 주소를 검색해주세요
          </h2>
          <p className="text-xs text-slate-400 mb-4">건물명, 단지명, 도로명 주소로 검색하세요</p>

          <div className="flex gap-2 mb-3">
            <input
              className="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              placeholder="예: 래미안원베일리, 서초구 반포동..."
              value={searchQuery}
              onChange={e => { setSearchQuery(e.target.value); setManualInput(false); }}
              onKeyDown={e => e.key === "Enter" && handleAddressSearch()}
              autoFocus
            />
            <button
              onClick={handleAddressSearch}
              disabled={searching}
              className="px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary-strong disabled:opacity-50 transition-colors"
            >
              {searching ? "검색 중..." : "검색"}
            </button>
          </div>

          {/* 검색 결과 */}
          {searchResults.length > 0 && (
            <ul className="border border-slate-200 rounded-lg divide-y max-h-64 overflow-y-auto mb-4">
              {searchResults.map((doc, i) => (
                <li
                  key={i}
                  className="px-4 py-3 text-sm cursor-pointer hover:bg-emerald-50 transition-colors"
                  onClick={() => selectAddress(doc)}
                >
                  <div className="font-medium text-slate-800">{doc.place_name || doc.address_name}</div>
                  {doc.place_name && (
                    <div className="text-xs text-slate-400 mt-0.5">{doc.road_address_name || doc.address_name}</div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {/* 선택된 주소 표시 */}
          {selectedAddress && !searchResults.length && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 flex items-center justify-between mb-4">
              <div>
                <div className="text-xs text-primary font-medium mb-0.5">선택된 주소</div>
                <div className="text-sm font-medium text-slate-800">{selectedAddress}</div>
                {buildingName && <div className="text-xs text-slate-500">{buildingName}</div>}
              </div>
              <button
                onClick={() => { setSelectedAddress(""); setBuildingName(""); }}
                className="text-slate-400 hover:text-red-500 ml-3 transition-colors"
              >✕</button>
            </div>
          )}

          {/* 직접 입력 */}
          {!selectedAddress && (
            <div className="mt-3">
              {!manualInput ? (
                <button
                  onClick={() => setManualInput(true)}
                  className="text-xs text-primary hover:underline"
                >
                  주소를 직접 입력하기
                </button>
              ) : (
                <input
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                  placeholder="예: 서울시 서초구 반포동 1번지"
                  autoFocus
                  value={selectedAddress}
                  onChange={e => setSelectedAddress(e.target.value)}
                />
              )}
            </div>
          )}

          <button
            onClick={() => setStep(3)}
            disabled={!selectedAddress}
            className="mt-5 w-full py-2.5 bg-primary text-white rounded-xl font-medium text-sm hover:bg-primary-strong disabled:opacity-40 transition-colors"
          >
            다음 단계 →
          </button>
        </section>
      )}

      {/* ── STEP 3 : 상세 정보 ───────────────────────── */}
      {step === 3 && (
        <section className="bg-white rounded-xl shadow p-6">
          <button onClick={goBack} className="text-sm text-slate-400 hover:text-slate-700 mb-4 flex items-center gap-1 transition-colors">
            ← 뒤로
          </button>

          <h2 className="font-semibold text-base text-slate-800 mb-4">상세 정보 입력</h2>
          <label className="mb-4 block text-sm">면적(㎡)<input aria-label="면적(㎡)" type="number" min="0.01" step="any" value={areaSqm} onChange={(event) => setAreaSqm(event.target.value)} className="mt-1 block w-full rounded-lg border px-3 py-2" /></label>
          <label className="mb-4 block text-sm">건물명<input value={buildingName} onChange={(event) => setBuildingName(event.target.value)} className="mt-1 block w-full rounded-lg border px-3 py-2" /></label>

          {/* 선택 요약 */}
          <div className="bg-slate-50 rounded-lg px-4 py-3 mb-5 text-sm flex flex-wrap gap-x-3 gap-y-1">
            <span><span className="text-slate-400">종류</span> <span className="font-medium text-slate-700">{selectedType?.label}</span></span>
            <span className="text-slate-300">|</span>
            <span><span className="text-slate-400">주소</span> <span className="font-medium text-slate-700">{selectedAddress}</span></span>
            {buildingName && (
              <>
                <span className="text-slate-300">|</span>
                <span className="font-medium text-slate-700">{buildingName}</span>
              </>
            )}
          </div>

          {/* 동 / 호수 */}
          {(selectedType?.hasDong || selectedType?.hasHo) && (
            <div className={`grid gap-3 mb-4 ${selectedType.hasDong ? "grid-cols-2" : "grid-cols-1"}`}>
              {selectedType.hasDong && (
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1">
                    동 <span className="text-slate-400 font-normal text-xs">(선택)</span>
                  </label>
                  <input
                    className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                    placeholder="예: 101동"
                    value={dongNo}
                    onChange={e => setDongNo(e.target.value)}
                  />
                </div>
              )}
              {selectedType.hasHo && (
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1">
                    호수 <span className="text-slate-400 font-normal text-xs">(선택)</span>
                  </label>
                  <input
                    className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                    placeholder="예: 201호"
                    value={hoNo}
                    onChange={e => setHoNo(e.target.value)}
                  />
                </div>
              )}
            </div>
          )}

          {/* 거래 유형 */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-600 mb-2">거래 유형</label>
            <div className="flex gap-2">
              {["매매", "전세", "월세"].map(t => (
                <button
                  key={t}
                  onClick={() => setTransactionType(t)}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    transactionType === t
                      ? "bg-primary text-white border-primary"
                      : "border-slate-300 text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* 기준시점 */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-600 mb-2">기준시점</label>
            <div className="flex gap-2 mb-2">
              <button
                onClick={() => setAppraisalDateType("current")}
                className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                  appraisalDateType === "current"
                    ? "bg-primary text-white border-primary"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50"
                }`}
              >
                현재 시점
              </button>
              <button
                onClick={() => setAppraisalDateType("custom")}
                className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                  appraisalDateType === "custom"
                    ? "bg-primary text-white border-primary"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50"
                }`}
              >
                날짜 지정
              </button>
            </div>
            {appraisalDateType === "custom" && (
              <input
                type="date"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                value={customDate}
                max={new Date().toISOString().split("T")[0]}
                onChange={e => setCustomDate(e.target.value)}
              />
            )}
          </div>

          {/* 조회 목적 */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-slate-600 mb-2">
              조회 목적 <span className="text-slate-400 font-normal text-xs">(선택)</span>
            </label>
            <div className="grid grid-cols-3 gap-2">
              {["", "담보", "경매", "과세", "매매", "보상", "임의"].map(p => (
                <button
                  key={p}
                  onClick={() => setAppraisalPurpose(p)}
                  className={`py-2 rounded-lg text-sm font-medium border transition-colors ${
                    appraisalPurpose === p
                      ? "bg-primary text-white border-primary"
                      : "border-slate-300 text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {p === "" ? "선택 안 함" : p}
                </button>
              ))}
            </div>
          </div>

          {error && <p className="text-red-500 text-sm mb-3">⚠️ {error}</p>}

          <button
            onClick={handleSubmit}
            disabled={loading}
            className="w-full py-3 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-primary-strong disabled:opacity-50 transition-colors"
          >
            {loading ? "AI 시세추정 실행 중... (30초~2분 소요)" : "시세추정 시작"}
          </button>
        </section>
      )}

      {loading && (() => {
        // 파이프라인 노드명 → 사용자 표시 단계 매핑
        const PIPELINE = [
          { match: ["의도분석", "검증"],        label: "요청 분석" },
          { match: ["지오코딩"],                label: "주소·입지 확인" },
          { match: ["심층분석"],                label: "실거래 데이터 수집" },
          { match: ["라우터", "_agent"],        label: "AI 가치 분석" },
          { match: ["리포트"],                  label: "리포트 생성" },
        ];
        let currentIdx = 0;
        PIPELINE.forEach((p, i) => {
          if (p.match.some(m => progressStep.includes(m))) currentIdx = i;
        });

        return (
          <div className="mt-4 bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm">
            <div className="font-semibold text-primary-strong mb-3">AI 시세추정 진행 중...</div>
            <div className="space-y-2">
              {PIPELINE.map((p, i) => {
                const done   = progressStep !== "" && i < currentIdx;
                const active = progressStep !== "" ? i === currentIdx : i === 0;
                return (
                  <div key={p.label} className="flex items-center gap-2.5">
                    <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${
                      done   ? "bg-primary text-white" :
                      active ? "bg-white border-2 border-primary text-primary animate-pulse" :
                               "bg-slate-200 text-slate-400"
                    }`}>
                      {done ? "✓" : i + 1}
                    </span>
                    <span className={
                      done   ? "text-primary-strong" :
                      active ? "text-primary-strong font-semibold" :
                               "text-slate-400"
                    }>
                      {p.label}{active && "..."}
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="text-xs text-primary/60 mt-3">보통 30초~2분 정도 소요됩니다. 페이지를 벗어나도 결과는 이력에 저장됩니다.</p>
          </div>
        );
      })()}
      </fieldset>
    </div>
  );
}
