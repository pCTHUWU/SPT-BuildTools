using System.Reflection;
using BepInEx;
using EFT.UI.Ragfair;
using HarmonyLib;
using SPT.Reflection.Patching;

namespace BuildScreenFilter
{
    /// <summary>
    /// Makes the buy-parts screen show flea offers, not trader stock only.
    ///
    /// This is the client half of SPT-BuildTools. The generated weapon and equipment builds reach
    /// for the best part available, and plenty of those parts no trader carries - so on the stock
    /// buy-parts screen they read NOT AVAILABLE with a blank price and the build looks broken when
    /// it is not.
    /// </summary>
    [BepInPlugin("com.oglok.buildscreenfilter", "BuildScreenFilter", "1.0.0")]
    public class BuildScreenFilterPlugin : BaseUnityPlugin
    {
        private void Awake()
        {
            new BuildFilterPatch().Enable();
            Logger.LogInfo("[BuildScreenFilter] buy-parts screen will show all offers, not just traders");
        }
    }

    /// <summary>
    /// Vanilla BSG behaviour, not a mod conflict. `RagFair._weaponBuildsFilterRule` hardcodes
    /// `OfferOwnerType = 1` (Traders) for `EViewListType.WeaponBuild`, while the ordinary flea
    /// (`DefaultFilterRule`, `AllOffers`) uses 0 (Any) - which is why only the build screen
    /// misbehaves. `GetPreferredRule` returns that hardcoded rule unless PlayerPrefs holds a
    /// `DefaultFilterRule_WeaponBuild` override, so with no saved override every visit is
    /// trader-only.
    ///
    /// It applies to EQUIPMENT builds too - the buy-parts flow for a saved kit uses the same view
    /// type - which is how it turned up here rather than only on weapons.
    ///
    /// `RagFair.ClearSavedFilters()` only empties an in-memory `_savedRules` list and does nothing
    /// to PlayerPrefs, so it is not the lever it sounds like. The non-mod alternative is the filter
    /// window's save-as-default, which writes the override permanently.
    ///
    /// `FilterRule` is a STRUCT, so the result must be taken by ref or the change lands on a copy
    /// and is thrown away. `OfferOwnerType` on it is a public field, not a property.
    /// </summary>
    public class BuildFilterPatch : ModulePatch
    {
        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(RagFair), nameof(RagFair.GetPreferredRule));
        }

        [PatchPostfix]
        public static void Postfix(EViewListType viewListType, ref FilterRule __result)
        {
            if (viewListType != EViewListType.WeaponBuild)
                return;

            // 0 = AnyOwnerType. Only widens what is listed; sorting, bartering and the condition
            // filters the player set themselves are untouched.
            __result.OfferOwnerType = (int)EOfferOwnerType.AnyOwnerType;
        }
    }
}
