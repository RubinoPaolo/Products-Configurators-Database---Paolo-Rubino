import Image from "next/image";
import { getCountryCode } from "@/lib/stickers";

type CountryFlagProps = {
  country?: string | null;
};

export default function CountryFlag({ country }: CountryFlagProps) {
  const countryCode = getCountryCode(country);

  if (!countryCode) {
    return (
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-lg shadow-lg">
        🌍
      </div>
    );
  }

  return (
    <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/5 p-2 shadow-lg">
      <Image
        src={`https://flagcdn.com/w40/${countryCode}.png`}
        alt={`${country ?? "Country"} flag`}
        width={28}
        height={20}
        className="rounded-sm object-cover"
      />
    </div>
  );
}