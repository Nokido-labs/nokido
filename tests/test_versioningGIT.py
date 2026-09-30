# test_version.py
import asyncio
from version_manager import VersionManager, ChangeType

async def main():

    # 1. Initialiser avec un faux fichier source
    vm = VersionManager("Nokido.py", author="user", use_git=False)  # use_git=False pour commencer
    print(f"\n✅ Version courante : {vm.current_version}")

    # 2. Lire le code actuel
    code = vm.current_code
    print(f"✅ Code chargé : {len(code)} caractères")

    # 3. Simuler un patch (correction mineure)
    code_modifie = code + "\n# patch de test\n"
    path = await vm.apply_patch(
        code_modifie,
        description="fix: test de patch mineur",
        change_type=ChangeType.PATCH
    )
    print(f"✅ PATCH appliqué → {path.name if path else 'ÉCHEC'}")
    print(f"   Nouvelle version : {vm.current_version}")

    # 4. Simuler une nouvelle feature
    code_modifie2 = code + "\n# nouvelle feature\n"
    path2 = await vm.apply_patch(
        code_modifie2,
        description="feat: test de feature mineure",
        change_type=ChangeType.MINOR
    )
    print(f"✅ MINOR appliqué  → {path2.name if path2 else 'ÉCHEC'}")
    print(f"   Nouvelle version : {vm.current_version}")

    # 5. Afficher l'historique
    print(f"\n📋 Historique :\n{vm.get_history_summary()}")

asyncio.run(main())