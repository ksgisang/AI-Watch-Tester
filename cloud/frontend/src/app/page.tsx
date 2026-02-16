import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-16">
      {/* Hero */}
      <section className="mb-16 text-center">
        <h1 className="mb-4 text-4xl font-bold tracking-tight text-gray-900">
          URL만 넣으면
          <br />
          <span className="text-blue-600">AI가 테스트합니다</span>
        </h1>
        <p className="mx-auto mb-8 max-w-xl text-lg text-gray-600">
          AWT Cloud는 웹사이트 URL을 입력하면 AI가 자동으로 테스트 시나리오를
          생성하고 Playwright로 실행합니다. 설치 없이 브라우저에서 바로.
        </p>
        <Link
          href="/signup"
          className="inline-block rounded-lg bg-blue-600 px-8 py-3 text-lg font-medium text-white hover:bg-blue-700"
        >
          무료로 시작하기
        </Link>
      </section>

      {/* How it works */}
      <section className="mb-16">
        <h2 className="mb-8 text-center text-2xl font-bold text-gray-900">
          How it works
        </h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {[
            {
              step: "1",
              title: "URL 입력",
              desc: "테스트할 웹사이트 주소를 입력하세요",
            },
            {
              step: "2",
              title: "AI 시나리오 생성",
              desc: "AI가 페이지를 분석하고 테스트 시나리오를 자동 생성합니다",
            },
            {
              step: "3",
              title: "결과 확인",
              desc: "실시간으로 테스트 진행을 보고 스크린샷과 함께 결과를 확인하세요",
            },
          ].map((item) => (
            <div
              key={item.step}
              className="rounded-lg border border-gray-200 p-6 text-center"
            >
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-blue-100 text-lg font-bold text-blue-600">
                {item.step}
              </div>
              <h3 className="mb-2 font-semibold text-gray-900">{item.title}</h3>
              <p className="text-sm text-gray-600">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section>
        <h2 className="mb-8 text-center text-2xl font-bold text-gray-900">
          Pricing
        </h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {/* Free */}
          <div className="rounded-lg border border-gray-200 p-6">
            <h3 className="mb-2 text-xl font-bold text-gray-900">Free</h3>
            <p className="mb-4 text-3xl font-bold text-gray-900">
              $0<span className="text-sm font-normal text-gray-500">/month</span>
            </p>
            <ul className="mb-6 space-y-2 text-sm text-gray-600">
              <li>&#10003; 5 tests / month</li>
              <li>&#10003; AI scenario generation</li>
              <li>&#10003; Screenshot results</li>
              <li>&#10003; Test history</li>
            </ul>
            <Link
              href="/signup"
              className="block rounded-lg border border-gray-300 py-2 text-center text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Get Started Free
            </Link>
          </div>

          {/* Pro */}
          <div className="rounded-lg border-2 border-blue-500 p-6">
            <h3 className="mb-2 text-xl font-bold text-gray-900">Pro</h3>
            <p className="mb-4 text-3xl font-bold text-gray-900">
              $29<span className="text-sm font-normal text-gray-500">/month</span>
            </p>
            <ul className="mb-6 space-y-2 text-sm text-gray-600">
              <li>&#10003; Unlimited monthly tests</li>
              <li>&#10003; 20 tests / day</li>
              <li>&#10003; Priority execution queue</li>
              <li>&#10003; Detailed analysis reports</li>
            </ul>
            <Link
              href="/signup"
              className="block rounded-lg bg-blue-600 py-2 text-center text-sm font-medium text-white hover:bg-blue-700"
            >
              Start Pro
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
