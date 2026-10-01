import ListingsWorkspace from "./ListingsWorkspace";
import type { ListingEntryContext } from "@/lib/listingNavigation";

export default async function ListingsPage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const text = (key: string, limit: number) => typeof params[key] === "string" ? params[key].trim().slice(0, limit) : "";
  const id = (key: string) => /^[1-9]\d{0,14}$/.test(text(key, 16)) ? text(key, 16) : "";
  const propertyType = text("property_type", 30);
  const entry: ListingEntryContext = {
    name: text("name", 150), address: text("address", 500), caseId: id("case_id"), listingId: id("listing_id"),
    propertyType: ["apartment", "officetel", "row_house", "detached", "non_residential", "industrial", "land"].includes(propertyType) ? propertyType : undefined,
  };
  return <ListingsWorkspace key={JSON.stringify(entry)} entry={entry} />;
}
