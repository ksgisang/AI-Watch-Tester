import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const headerStore = await headers();

  // 1. Cookie (user preference)
  let locale = cookieStore.get("NEXT_LOCALE")?.value;

  // 2. Accept-Language header fallback
  if (!locale) {
    const acceptLang = headerStore.get("accept-language") || "";
    if (acceptLang.startsWith("ko") || acceptLang.includes(",ko")) {
      locale = "ko";
    }
  }

  // 3. Default
  if (!locale || !["en", "ko"].includes(locale)) {
    locale = "en";
  }

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
