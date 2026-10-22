"""
Unit tests for app.core.crypto (AES-256-GCM encryption & EncryptedString).
"""
from sqlalchemy import Column, Integer, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.crypto import EncryptedString, decrypt_field, encrypt_field


def test_encrypt_decrypt_roundtrip():
    plaintext = "TR330006100511123456789012"
    ciphertext = encrypt_field(plaintext)
    assert ciphertext is not None
    assert ciphertext.startswith("enc:v1:")
    assert ciphertext != plaintext

    decrypted = decrypt_field(ciphertext)
    assert decrypted == plaintext


def test_turkish_and_unicode_characters():
    text = "Şirket Ünvanı: Çalık Holding A.Ş. — Vergi Dairesi: Beşiktaş — Tutar: 1.500.000,50 ₺"
    ciphertext = encrypt_field(text)
    assert ciphertext is not None
    assert decrypt_field(ciphertext) == text


def test_none_handling():
    assert encrypt_field(None) is None
    assert decrypt_field(None) is None


def test_already_encrypted_not_double_encrypted():
    text = "secret-tax-id-123456"
    c1 = encrypt_field(text)
    c2 = encrypt_field(c1)
    assert c1 == c2


def test_unencrypted_legacy_backward_compatibility():
    legacy_plain = "legacy_plain_tax_id_9999"
    decrypted = decrypt_field(legacy_plain)
    assert decrypted == legacy_plain


def test_tampered_ciphertext_handled_gracefully():
    text = "confidential-financial-report"
    ct = encrypt_field(text)
    assert ct is not None
    # Tamper with the base64 content
    tampered = ct[:-3] + "XYZ"
    result = decrypt_field(tampered)
    # Tampered ciphertext fails authentication gracefully
    assert result == tampered


class Base(DeclarativeBase):
    pass


class SecretModel(Base):
    __tablename__ = "test_secrets"

    id = Column(Integer, primary_key=True)
    vkn = Column(EncryptedString)
    iban = Column(EncryptedString)


def test_sqlalchemy_encrypted_string_decorator():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        item = SecretModel(id=1, vkn="1234567890", iban="TR990001000100010001000100")
        session.add(item)
        session.commit()

    # Verify that in raw DB, the values are encrypted
    with engine.connect() as conn:
        from sqlalchemy import text
        row = conn.execute(text("SELECT vkn, iban FROM test_secrets WHERE id = 1")).fetchone()
        assert row is not None
        assert row[0].startswith("enc:v1:")
        assert row[1].startswith("enc:v1:")
        assert "1234567890" not in row[0]

    # Verify that reading through ORM decrypts automatically
    with Session(engine) as session:
        loaded = session.scalar(select(SecretModel).where(SecretModel.id == 1))
        assert loaded is not None
        assert loaded.vkn == "1234567890"
        assert loaded.iban == "TR990001000100010001000100"
