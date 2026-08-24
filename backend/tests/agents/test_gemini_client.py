import pytest
from sqlalchemy.orm import Session

from app.agents.gemini_client import GeminiConfigurationError, build_client, declare_tools
from app.agents.tools.catalog import GetProductTool, SearchCatalogTool
from app.core.config import Settings


def test_build_client_raises_without_api_key() -> None:
    settings = Settings(_env_file=None, gemini_api_key=None)

    with pytest.raises(GeminiConfigurationError):
        build_client(settings)


def test_build_client_succeeds_with_api_key() -> None:
    settings = Settings(_env_file=None, gemini_api_key="test-key")

    client = build_client(settings)

    assert client is not None


def test_declare_tools_exposes_name_description_and_input_schema(db_session: Session) -> None:
    tools = [SearchCatalogTool(db_session), GetProductTool(db_session)]

    declared = declare_tools(tools)

    assert len(declared) == 1
    declarations = declared[0].function_declarations
    assert [d.name for d in declarations] == ["search_catalog", "get_product"]

    search_decl = declarations[0]
    assert search_decl.description == SearchCatalogTool.description
    assert search_decl.parameters_json_schema == SearchCatalogTool.input_model.model_json_schema()

    get_decl = declarations[1]
    assert get_decl.parameters_json_schema == GetProductTool.input_model.model_json_schema()


def test_declare_tools_only_ever_exposes_catalog_tools(db_session: Session) -> None:
    """No tool outside the catalog module can be smuggled into what Gemini sees."""
    tools = [SearchCatalogTool(db_session), GetProductTool(db_session)]

    declared_names = {d.name for d in declare_tools(tools)[0].function_declarations}

    assert declared_names == {"search_catalog", "get_product"}
